"""Property-based tests for the extraction endpoint (Task 6.3).

This module holds the Hypothesis property tests that exercise
``POST /buy-boxes/extract`` over generated input spaces. It is kept separate
from the example-based extraction integration tests so the two suites can
evolve without write conflicts.

The tests inject two seams so no live AI provider or database is touched:

* A **recording provider** is injected via ``app.dependency_overrides`` for
  :func:`api.main.get_extraction_provider`. It records whether it was ever
  invoked; the extraction route only calls it once a request body passes
  validation, so a rejected request must leave it untouched.
* A **recording Supabase client** is injected via :func:`api.db.set_client`.
  It records every table operation, so a rejected request must leave it empty
  (nothing persisted).
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

import api.main as main
from api import db

# --------------------------------------------------------------------------- #
# Recording seams (provider + database) — neither should fire on a rejected
# whitespace-only request.
# --------------------------------------------------------------------------- #


class _RecordingProvider:
    """A provider callable ``(system, user) -> str`` that records invocation.

    The extraction route only calls the provider after the request body passes
    validation. For a whitespace-only ``raw_text`` the body is rejected at the
    Pydantic edge, so ``called`` must stay ``False``.
    """

    def __init__(self) -> None:
        self.called = False

    def __call__(self, system: str, user: str) -> str:
        self.called = True
        return "{}"


class _Response:
    def __init__(self, data: list) -> None:
        self.data = data


class _RecordingQuery:
    """Minimal query-builder stand-in that records the operation it ran."""

    def __init__(self, client: "_RecordingClient", name: str) -> None:
        self._client = client
        self._name = name

    def insert(self, payload):
        self._client.operations.append(("insert", self._name, payload))
        return self

    def select(self, columns):
        self._client.operations.append(("select", self._name, columns))
        return self

    def delete(self):
        self._client.operations.append(("delete", self._name))
        return self

    def eq(self, column, value):
        return self

    def execute(self):
        return _Response([])


class _RecordingClient:
    """A Supabase client stand-in that records every table operation."""

    def __init__(self) -> None:
        self.operations: list[tuple] = []

    def table(self, name: str) -> _RecordingQuery:
        return _RecordingQuery(self, name)


#: A single TestClient over the app; dependency overrides are applied per test.
_client = TestClient(main.app)


# --------------------------------------------------------------------------- #
# Strategy: whitespace-only and empty strings.
#
# The ExtractRequest validator rejects ``raw_text`` whenever ``v.strip()`` is
# empty; the field's ``min_length=1`` additionally rejects ``""``. Both paths
# yield HTTP 422. This strategy draws from common ASCII whitespace so every
# generated value (including the empty string) is whitespace-only.
# --------------------------------------------------------------------------- #

_WHITESPACE_CHARS = " \t\n\r\x0b\x0c"

whitespace_or_empty_text = st.text(
    alphabet=_WHITESPACE_CHARS, min_size=0, max_size=30
)


# Feature: buybox-matcher, Property 15: Whitespace-only raw_text is rejected
# Validates: Requirements 1.8
#
# When a POST /buy-boxes/extract request carries a raw_text that is missing,
# empty, or contains only whitespace, the API must respond with HTTP 422 and
# must NOT invoke the AI provider and must NOT persist any data. Across the
# generated space of whitespace-only and empty strings, every request must be
# rejected at the validation edge — the injected recording provider stays
# uninvoked and the injected recording database client records no operations.
@settings(max_examples=200)
@given(raw_text=whitespace_or_empty_text)
def test_property_15_whitespace_only_raw_text_is_rejected(raw_text):
    recording_provider = _RecordingProvider()
    fake_db = _RecordingClient()

    db.set_client(fake_db)
    main.app.dependency_overrides[main.get_extraction_provider] = (
        lambda: recording_provider
    )
    try:
        response = _client.post("/buy-boxes/extract", json={"raw_text": raw_text})

        # Rejected at the validation edge (Req 1.8).
        assert response.status_code == 422
        # The AI provider was never invoked (Req 1.8).
        assert recording_provider.called is False
        # Nothing was persisted (Req 1.8).
        assert fake_db.operations == []
    finally:
        main.app.dependency_overrides.clear()
        db.reset_client()


# --------------------------------------------------------------------------- #
# Property 16: Price-range validation invariant (Task 6.4)
#
# A non-null ``(price_min, price_max)`` pair is accepted iff
# ``price_min <= price_max``; otherwise the API responds 422 and persists
# nothing. The price-range invariant lives in ``BuyBoxModel.price_range_valid``;
# the extraction route surfaces a violation as a validation ExtractionError ->
# HTTP 422 (Req 1.10), and a valid pair is persisted 1:1 and returned 201
# (Req 1.11).
#
# The success path needs a database client that echoes inserted rows (with a
# generated id) so the buyer + buy_box persist and the route can build its 201
# body. The recording client above returns no rows, so this section uses a
# small in-memory client instead.
# --------------------------------------------------------------------------- #


class _InMemoryResponse:
    def __init__(self, data: list) -> None:
        self.data = data


class _InMemoryQuery:
    """In-memory query builder that actually stores/echoes inserted rows."""

    def __init__(self, client: "_InMemoryClient", name: str) -> None:
        self._client = client
        self._name = name
        self._op: str | None = None
        self._payload = None
        self._filters: list[tuple[str, object]] = []

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def select(self, _columns):
        self._op = "select"
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def execute(self):
        if self._op == "insert":
            row = dict(self._payload)
            self._client._counter += 1
            row.setdefault("id", f"{self._name[:-1]}-{self._client._counter}")
            self._client.rows.setdefault(self._name, []).append(row)
            return _InMemoryResponse([row])
        if self._op == "select":
            return _InMemoryResponse(list(self._client.rows.get(self._name, [])))
        if self._op == "delete":
            kept, removed = [], []
            for row in self._client.rows.get(self._name, []):
                if all(row.get(col) == val for col, val in self._filters):
                    removed.append(row)
                else:
                    kept.append(row)
            self._client.rows[self._name] = kept
            return _InMemoryResponse(removed)
        return _InMemoryResponse([])


class _InMemoryClient:
    """A Supabase client stand-in that persists rows in memory."""

    def __init__(self) -> None:
        self.rows: dict[str, list[dict]] = {}
        self._counter = 0

    def table(self, name: str) -> _InMemoryQuery:
        return _InMemoryQuery(self, name)

    def total_rows(self) -> int:
        return sum(len(v) for v in self.rows.values())


def _buy_box_json(price_min: int, price_max: int) -> str:
    """A complete, valid Buy_Box JSON differing only in the price pair."""
    import json as _json

    return _json.dumps(
        {
            "markets": ["Tampa"],
            "strategy": "fix_and_flip",
            "property_type": "single_family",
            "price_min": price_min,
            "price_max": price_max,
            "arv_pct_max": 70,
            "min_beds": 3,
            "min_baths": 2.0,
            "condition": "distressed",
        }
    )


# A pair of non-null integer prices. Independent draws span both
# ``price_min <= price_max`` and ``price_min > price_max`` cases.
price_pairs = st.tuples(
    st.integers(min_value=0, max_value=2_000_000),
    st.integers(min_value=0, max_value=2_000_000),
)


# Feature: buybox-matcher, Property 16: Price-range validation invariant
# Validates: Requirements 1.10
#
# For a non-null (price_min, price_max) pair produced by extraction, the API
# accepts the buy box (HTTP 201, buyer + buy_box persisted) iff
# price_min <= price_max. When price_min > price_max the API responds HTTP 422
# and persists nothing. The provider returns a JSON buy box carrying exactly
# the generated prices; everything else in the buy box is fixed and valid so
# the price range is the sole determinant of acceptance.
@settings(max_examples=150)
@given(prices=price_pairs)
def test_property_16_price_range_validation_invariant(prices):
    price_min, price_max = prices

    fake_db = _InMemoryClient()
    provider = lambda system, user: _buy_box_json(price_min, price_max)

    db.set_client(fake_db)
    main.app.dependency_overrides[main.get_extraction_provider] = lambda: provider
    try:
        response = _client.post(
            "/buy-boxes/extract", json={"raw_text": "an investor message"}
        )

        if price_min <= price_max:
            # Accepted: 201 with the echoed price pair, buyer + buy_box stored.
            assert response.status_code == 201
            body = response.json()
            assert body["buy_box"]["price_min"] == price_min
            assert body["buy_box"]["price_max"] == price_max
            assert len(fake_db.rows.get(db.BUYERS_TABLE, [])) == 1
            assert len(fake_db.rows.get(db.BUY_BOXES_TABLE, [])) == 1
        else:
            # Rejected: 422 and nothing persisted (Req 1.10).
            assert response.status_code == 422
            assert fake_db.rows.get(db.BUYERS_TABLE, []) == []
            assert fake_db.rows.get(db.BUY_BOXES_TABLE, []) == []
    finally:
        main.app.dependency_overrides.clear()
        db.reset_client()
