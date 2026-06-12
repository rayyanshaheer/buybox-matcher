"""Integration tests for the extraction + buyers endpoints (Task 6.5).

These exercise ``POST /buy-boxes/extract`` and ``GET /buyers`` end to end with a
**mocked AI provider** and an injected in-memory database client, so they need
neither the ``openai``/``anthropic`` SDKs nor live Supabase credentials.

Coverage (Req 1.1, 1.3, 1.7, 1.9, 1.11, 10.2, 10.3):

* valid provider JSON -> 201 with ``{buyer_id, buy_box}`` and a persisted buyer;
* partial information -> absent fields come back ``null`` (no inference, Req 1.3);
* non-JSON provider output -> 422, nothing persisted (Req 1.7, 10.2);
* provider error -> upstream error status, nothing persisted (Req 1.9);
* provider timeout -> upstream error status, nothing persisted (Req 1.9);
* ``GET /buyers`` happy path and empty-array cases (Req 10.3).

The provider is injected through ``main.get_extraction_provider`` (a FastAPI
dependency seam) so the full extraction pipeline runs against the mock with no
live API call.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

import api.db as db
import api.main as main


# --------------------------------------------------------------------------- #
# In-memory fake Supabase client (mirrors the one in test_db.py)
# --------------------------------------------------------------------------- #


class _FakeQuery:
    def __init__(self, table: "_FakeTable", op: str):
        self._table = table
        self._op = op
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
        return self._table.run(self._op, self._payload, self._filters)


class _Response:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, client: "_FakeClient", name: str):
        self._client = client
        self._name = name

    def insert(self, payload):
        return _FakeQuery(self, "insert").insert(payload)

    def select(self, columns):
        return _FakeQuery(self, "select").select(columns)

    def delete(self):
        return _FakeQuery(self, "delete").delete()

    def run(self, op, payload, filters):
        self._client.calls.append((self._name, op, payload, filters))
        if op == "insert":
            return self._client.handle_insert(self._name, payload)
        if op == "select":
            return self._client.handle_select(self._name)
        if op == "delete":
            return self._client.handle_delete(self._name, filters)
        raise AssertionError(f"unexpected op {op}")


class _FakeClient:
    """Minimal in-memory stand-in for the Supabase client used by api.db."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.rows: dict[str, list[dict]] = {
            db.BUYERS_TABLE: [],
            db.BUY_BOXES_TABLE: [],
            db.PROPERTIES_TABLE: [],
            db.MATCHES_TABLE: [],
        }
        self._next_id = 0

    def table(self, name):
        return _FakeTable(self, name)

    def _gen_id(self, prefix):
        self._next_id += 1
        return f"{prefix}-{self._next_id}"

    def handle_insert(self, name, payload):
        row = dict(payload)
        row.setdefault("id", self._gen_id(name[:-1]))
        self.rows[name].append(row)
        return _Response([row])

    def handle_select(self, name):
        if name == db.BUYERS_TABLE:
            out = []
            for buyer in self.rows[db.BUYERS_TABLE]:
                embedded = [
                    bb
                    for bb in self.rows[db.BUY_BOXES_TABLE]
                    if bb.get("buyer_id") == buyer["id"]
                ]
                merged = dict(buyer)
                merged[db.BUY_BOXES_TABLE] = embedded
                out.append(merged)
            return _Response(out)
        return _Response(list(self.rows[name]))

    def handle_delete(self, name, filters):
        kept, removed = [], []
        for row in self.rows[name]:
            if all(row.get(col) == val for col, val in filters):
                removed.append(row)
            else:
                kept.append(row)
        self.rows[name] = kept
        return _Response(removed)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def fake_db():
    """Inject an in-memory db client for the duration of a test."""
    client = _FakeClient()
    db.set_client(client)
    try:
        yield client
    finally:
        db.reset_client()


@pytest.fixture
def client():
    """A TestClient whose dependency overrides are reset after each test."""
    test_client = TestClient(main.app)
    try:
        yield test_client
    finally:
        main.app.dependency_overrides.clear()


def _use_provider(provider_callable) -> None:
    """Override the extraction provider seam with a mock callable."""
    main.app.dependency_overrides[main.get_extraction_provider] = (
        lambda: provider_callable
    )


def _full_buy_box_json(**overrides) -> str:
    """A complete, valid Buy_Box JSON payload (all nine fields present)."""
    payload = {
        "markets": ["Tampa", "Orlando"],
        "strategy": "fix_and_flip",
        "property_type": "single_family",
        "price_min": 100_000,
        "price_max": 250_000,
        "arv_pct_max": 70,
        "min_beds": 3,
        "min_baths": 2.0,
        "condition": "distressed",
    }
    payload.update(overrides)
    return json.dumps(payload)


# --------------------------------------------------------------------------- #
# Valid JSON -> 201 (Req 1.1, 1.11, 10.1)
# --------------------------------------------------------------------------- #


def test_valid_json_returns_201_and_persists_buyer(fake_db, client):
    def provider(system: str, user: str) -> str:
        return _full_buy_box_json()

    _use_provider(provider)

    response = client.post(
        "/buy-boxes/extract",
        json={
            "raw_text": "distressed SFH in Tampa or Orlando, 100k-250k, 70% ARV, 3bd/2ba, flip",
            "name": "Jane Investor",
            "company": "Acme Capital",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["buyer_id"]
    assert body["buy_box"]["markets"] == ["Tampa", "Orlando"]
    assert body["buy_box"]["strategy"] == "fix_and_flip"
    assert body["buy_box"]["arv_pct_max"] == 70

    # Buyer + buy_box persisted 1:1 (Req 1.11).
    assert len(fake_db.rows[db.BUYERS_TABLE]) == 1
    assert len(fake_db.rows[db.BUY_BOXES_TABLE]) == 1
    stored_bb = fake_db.rows[db.BUY_BOXES_TABLE][0]
    assert stored_bb["buyer_id"] == body["buyer_id"]
    # raw_text (a required buy_box column, not part of the extracted schema) is
    # attached on persistence.
    assert stored_bb["raw_text"]


# --------------------------------------------------------------------------- #
# Partial information -> absent fields are null, never inferred (Req 1.3)
# --------------------------------------------------------------------------- #


def test_partial_json_keeps_absent_fields_null(fake_db, client):
    # The message only mentions a market and a strategy; everything else must
    # come back null (the provider obeys the null-for-absent rule).
    def provider(system: str, user: str) -> str:
        return json.dumps(
            {
                "markets": ["Cleveland"],
                "strategy": "wholesale",
                "property_type": None,
                "price_min": None,
                "price_max": None,
                "arv_pct_max": None,
                "min_beds": None,
                "min_baths": None,
                "condition": None,
            }
        )

    _use_provider(provider)

    response = client.post(
        "/buy-boxes/extract",
        json={"raw_text": "wholesaler buying anything in Cleveland"},
    )

    assert response.status_code == 201
    buy_box = response.json()["buy_box"]
    assert buy_box["markets"] == ["Cleveland"]
    assert buy_box["strategy"] == "wholesale"
    # No inference: every unmentioned field is null (Req 1.3).
    for field in (
        "property_type",
        "price_min",
        "price_max",
        "arv_pct_max",
        "min_beds",
        "min_baths",
        "condition",
    ):
        assert buy_box[field] is None


# --------------------------------------------------------------------------- #
# Non-JSON provider output -> 422, nothing persisted (Req 1.7, 10.2)
# --------------------------------------------------------------------------- #


def test_non_json_output_returns_422_and_persists_nothing(fake_db, client):
    def provider(system: str, user: str) -> str:
        return "Sure! Here is the buy box you asked for: it's a great deal."

    _use_provider(provider)

    response = client.post(
        "/buy-boxes/extract",
        json={"raw_text": "some investor message"},
    )

    assert response.status_code == 422
    assert fake_db.rows[db.BUYERS_TABLE] == []
    assert fake_db.rows[db.BUY_BOXES_TABLE] == []


def test_out_of_vocabulary_enum_returns_422_and_persists_nothing(fake_db, client):
    # Valid JSON, but an out-of-vocabulary enum fails Buy_Box validation -> 422.
    def provider(system: str, user: str) -> str:
        return _full_buy_box_json(strategy="flipping_houses")

    _use_provider(provider)

    response = client.post(
        "/buy-boxes/extract",
        json={"raw_text": "some investor message"},
    )

    assert response.status_code == 422
    assert fake_db.rows[db.BUYERS_TABLE] == []
    assert fake_db.rows[db.BUY_BOXES_TABLE] == []


# --------------------------------------------------------------------------- #
# Provider error / timeout -> error status, nothing persisted (Req 1.9)
# --------------------------------------------------------------------------- #


def test_provider_error_returns_error_status_and_persists_nothing(fake_db, client):
    def provider(system: str, user: str) -> str:
        raise RuntimeError("upstream provider exploded")

    _use_provider(provider)

    response = client.post(
        "/buy-boxes/extract",
        json={"raw_text": "some investor message"},
    )

    assert response.status_code >= 500
    assert response.status_code == 502
    assert fake_db.rows[db.BUYERS_TABLE] == []
    assert fake_db.rows[db.BUY_BOXES_TABLE] == []


def test_provider_timeout_returns_error_status_and_persists_nothing(fake_db, client):
    def slow_provider(system: str, user: str) -> str:
        time.sleep(0.2)
        return _full_buy_box_json()

    _use_provider(slow_provider)
    # Drive the timeout fast: override the timeout seam to a tiny value.
    main.app.dependency_overrides[main.get_extraction_timeout] = lambda: 0.05

    response = client.post(
        "/buy-boxes/extract",
        json={"raw_text": "some investor message"},
    )

    assert response.status_code == 504
    assert fake_db.rows[db.BUYERS_TABLE] == []
    assert fake_db.rows[db.BUY_BOXES_TABLE] == []


# --------------------------------------------------------------------------- #
# Whitespace-only raw_text -> 422 before the provider is invoked (Req 1.8)
# --------------------------------------------------------------------------- #


def test_whitespace_raw_text_returns_422_without_invoking_provider(fake_db, client):
    invoked = {"count": 0}

    def provider(system: str, user: str) -> str:  # pragma: no cover - must not run
        invoked["count"] += 1
        return _full_buy_box_json()

    _use_provider(provider)

    response = client.post("/buy-boxes/extract", json={"raw_text": "   \n\t  "})

    assert response.status_code == 422
    assert invoked["count"] == 0
    assert fake_db.rows[db.BUYERS_TABLE] == []


# --------------------------------------------------------------------------- #
# GET /buyers (Req 10.3)
# --------------------------------------------------------------------------- #


def test_get_buyers_empty_returns_empty_array(fake_db, client):
    response = client.get("/buyers")
    assert response.status_code == 200
    assert response.json() == []


def test_get_buyers_happy_path_lists_extracted_buyer(fake_db, client):
    def provider(system: str, user: str) -> str:
        return _full_buy_box_json()

    _use_provider(provider)

    extract_response = client.post(
        "/buy-boxes/extract",
        json={
            "raw_text": "distressed SFH in Tampa, flip",
            "name": "Jane Investor",
            "company": "Acme Capital",
        },
    )
    assert extract_response.status_code == 201
    buyer_id = extract_response.json()["buyer_id"]

    response = client.get("/buyers")
    assert response.status_code == 200
    buyers = response.json()
    assert len(buyers) == 1
    buyer = buyers[0]
    assert buyer["buyer_id"] == buyer_id
    assert buyer["name"] == "Jane Investor"
    assert buyer["company"] == "Acme Capital"
    assert buyer["buy_box"] is not None
    assert buyer["buy_box"]["strategy"] == "fix_and_flip"
