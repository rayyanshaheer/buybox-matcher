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
