"""Integration tests for ``POST /match`` (Req 7.1, 7.2, 7.4, 7.5, 7.8, 10.4, 10.8).

These tests drive the route end-to-end through a FastAPI ``TestClient`` while
injecting a minimal in-memory fake Supabase client (the same query-builder
stand-in shape used by ``test_db.py``), so they need neither the ``supabase``
package nor live credentials. The fake captures every persisted row, letting
the suite assert both the HTTP contract *and* that nothing is persisted on a
rejected request.

Coverage:

* Happy path — 200 with ``property_id`` and matches sorted by ``score`` desc
  then ``buyer_id`` asc, with each Match persisted (Req 7.1, 7.2, 7.3, 7.4, 10.4).
* Empty buyer set — 200 with an empty ``matches`` array (Req 7.5).
* ``min_score`` filtering and ``limit`` truncation (Req 7.6, 7.7 surfaced via
  the route).
* Invalid query param — 422 with nothing persisted (Req 7.8).
* Malformed body — 422 with nothing persisted (Req 10.8).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import db
import api.main as main


# --------------------------------------------------------------------------- #
# In-memory fake Supabase client (same shape as test_db.py's stand-in)
# --------------------------------------------------------------------------- #


class _Response:
    def __init__(self, data):
        self.data = data


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
    """A minimal in-memory fake of the Supabase client used by api.db."""

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
    """Inject an in-memory fake client for the duration of a test."""
    fake = _FakeClient()
    db.set_client(fake)
    try:
        yield fake
    finally:
        db.reset_client()


@pytest.fixture
def client():
    return TestClient(main.app)


# --------------------------------------------------------------------------- #
# Test data builders
# --------------------------------------------------------------------------- #


def _property_payload(**overrides):
    """A valid POST /match body for a distressed Tampa single-family deal.

    Deal_ARV_Pct = 150000 / 220000 * 100 = 68.18 (under a 70% ceiling).
    """
    payload = {
        "address": "123 Main St",
        "city": "Tampa",
        "price": 150_000,
        "arv": 220_000,
        "beds": 3,
        "baths": 2.0,
        "sqft": 1500,
        "property_type": "single_family",
        "condition": "distressed",
    }
    payload.update(overrides)
    return payload


def _add_buyer(fake: _FakeClient, *, name: str, buy_box: dict) -> str:
    """Persist a buyer + buy_box through the real db helper; return buyer_id."""
    result = db.insert_buyer_with_buy_box(name=name, buy_box=buy_box, client=fake)
    return result["buyer_id"]


def _perfect_buy_box():
    """Scores 100 against ``_property_payload`` (every component full credit)."""
    return {
        "markets": ["Tampa"],
        "strategy": "fix_and_flip",  # distressed suits fix_and_flip -> 20
        "property_type": "single_family",
        "price_min": 100_000,
        "price_max": 200_000,
        "arv_pct_max": 70,  # 68.18 <= 70 -> 15
        "min_beds": 3,
        "min_baths": 2.0,
        "condition": "distressed",
        "raw_text": "distressed SFH in Tampa under 200k",
    }


def _mid_buy_box():
    """Scores 80: market/price/arv/type/beds hit, strategy mismatch (-20)."""
    return {
        "markets": ["Tampa"],
        "strategy": "buy_and_hold",  # distressed does NOT suit buy_and_hold -> 0
        "property_type": "single_family",
        "price_min": 100_000,
        "price_max": 200_000,
        "arv_pct_max": 70,
        "min_beds": 3,
        "min_baths": 2.0,
        "condition": "turnkey",
        "raw_text": "turnkey SFH hold in Tampa",
    }


def _capped_buy_box():
    """Scores <= 25: city outside markets triggers the hard-filter cap."""
    return {
        "markets": ["Orlando"],  # Tampa not in markets -> Market 0 -> cap 25
        "strategy": "fix_and_flip",
        "property_type": "single_family",
        "price_min": 100_000,
        "price_max": 200_000,
        "arv_pct_max": 70,
        "min_beds": 3,
        "min_baths": 2.0,
        "condition": "distressed",
        "raw_text": "distressed SFH in Orlando",
    }


# --------------------------------------------------------------------------- #
# Happy path (Req 7.1, 7.2, 7.3, 7.4, 10.4)
# --------------------------------------------------------------------------- #


def test_match_happy_path_returns_200_sorted_and_persists(fake_db, client):
    buyer_perfect = _add_buyer(fake_db, name="Perfect", buy_box=_perfect_buy_box())
    buyer_mid = _add_buyer(fake_db, name="Mid", buy_box=_mid_buy_box())
    buyer_capped = _add_buyer(fake_db, name="Capped", buy_box=_capped_buy_box())

    response = client.post("/match", json=_property_payload())

    assert response.status_code == 200
    body = response.json()

    # property_id present and the property was persisted (Req 7.1, 10.4).
    assert body["property_id"]
    assert len(fake_db.rows[db.PROPERTIES_TABLE]) == 1
    assert body["property_id"] == fake_db.rows[db.PROPERTIES_TABLE][0]["id"]

    matches = body["matches"]
    assert len(matches) == 3

    # Sorted by score descending (Req 7.3, 7.4): perfect(100) > mid(80) > capped(<=25).
    scores = [m["score"] for m in matches]
    assert scores == sorted(scores, reverse=True)
    assert matches[0]["buyer_id"] == buyer_perfect
    assert matches[0]["score"] == 100
    assert matches[1]["buyer_id"] == buyer_mid
    assert matches[1]["score"] == 80
    assert matches[2]["buyer_id"] == buyer_capped
    assert matches[2]["score"] <= 25

    # Each Match persisted with score + reasons (Req 7.2).
    assert len(fake_db.rows[db.MATCHES_TABLE]) == 3
    for row in fake_db.rows[db.MATCHES_TABLE]:
        assert "score" in row
        assert "fit" in row["reasons"] and "risk" in row["reasons"]
        assert row["property_id"] == body["property_id"]

    # Each returned match carries fit/risk reasons (Req 2.4 surfaced via route).
    for m in matches:
        assert isinstance(m["reasons"]["fit"], list)
        assert isinstance(m["reasons"]["risk"], list)


def test_match_ties_broken_by_buyer_id_ascending(fake_db, client):
    # Two identical buy boxes -> identical scores; tie-break is buyer_id asc (Req 7.3).
    first = _add_buyer(fake_db, name="A", buy_box=_perfect_buy_box())
    second = _add_buyer(fake_db, name="B", buy_box=_perfect_buy_box())

    response = client.post("/match", json=_property_payload())

    assert response.status_code == 200
    matches = response.json()["matches"]
    assert [m["score"] for m in matches] == [100, 100]
    # Equal scores -> ascending buyer_id ordering.
    assert [m["buyer_id"] for m in matches] == sorted([first, second])


# --------------------------------------------------------------------------- #
# Empty buyer set (Req 7.5)
# --------------------------------------------------------------------------- #


def test_match_with_no_buyers_returns_200_empty_matches(fake_db, client):
    response = client.post("/match", json=_property_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["property_id"]
    assert body["matches"] == []
    # The property is still persisted even with no buyers to score (Req 7.1).
    assert len(fake_db.rows[db.PROPERTIES_TABLE]) == 1
    # No buyers -> no matches persisted.
    assert fake_db.rows[db.MATCHES_TABLE] == []


# --------------------------------------------------------------------------- #
# min_score filter and limit (Req 7.6, 7.7 surfaced via the route)
# --------------------------------------------------------------------------- #


def test_match_min_score_filters_results(fake_db, client):
    _add_buyer(fake_db, name="Perfect", buy_box=_perfect_buy_box())  # 100
    _add_buyer(fake_db, name="Mid", buy_box=_mid_buy_box())  # 80
    _add_buyer(fake_db, name="Capped", buy_box=_capped_buy_box())  # <= 25

    response = client.post("/match?min_score=80", json=_property_payload())

    assert response.status_code == 200
    matches = response.json()["matches"]
    # Only the two >= 80 matches are returned; the capped one is filtered out.
    assert len(matches) == 2
    assert all(m["score"] >= 80 for m in matches)


def test_match_limit_truncates_after_sorting(fake_db, client):
    _add_buyer(fake_db, name="Perfect", buy_box=_perfect_buy_box())  # 100
    _add_buyer(fake_db, name="Mid", buy_box=_mid_buy_box())  # 80
    _add_buyer(fake_db, name="Capped", buy_box=_capped_buy_box())  # <= 25

    response = client.post("/match?limit=1", json=_property_payload())

    assert response.status_code == 200
    matches = response.json()["matches"]
    # Only the single top-scoring match survives the limit.
    assert len(matches) == 1
    assert matches[0]["score"] == 100


def test_match_min_score_applied_before_limit(fake_db, client):
    _add_buyer(fake_db, name="Perfect", buy_box=_perfect_buy_box())  # 100
    _add_buyer(fake_db, name="Mid", buy_box=_mid_buy_box())  # 80
    _add_buyer(fake_db, name="Capped", buy_box=_capped_buy_box())  # <= 25

    # Filter to >= 80 (two matches) then cap at 5: filter happens first so the
    # capped match never occupies a limit slot (Req 7.6, 7.7).
    response = client.post("/match?min_score=80&limit=5", json=_property_payload())

    assert response.status_code == 200
    matches = response.json()["matches"]
    assert len(matches) == 2
    assert all(m["score"] >= 80 for m in matches)


# --------------------------------------------------------------------------- #
# Invalid query parameter -> 422, nothing persisted (Req 7.8)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "query",
    [
        "min_score=150",  # above the 0..100 range
        "min_score=-1",  # below the range
        "min_score=abc",  # not an integer
        "limit=0",  # below the >= 1 minimum
        "limit=-3",  # negative
        "limit=foo",  # not an integer
    ],
)
def test_match_invalid_query_param_returns_422_and_persists_nothing(
    fake_db, client, query
):
    _add_buyer(fake_db, name="Perfect", buy_box=_perfect_buy_box())
    persisted_before = list(fake_db.rows[db.PROPERTIES_TABLE])

    response = client.post(f"/match?{query}", json=_property_payload())

    assert response.status_code == 422
    # Validation happens at the edge: no property and no match are persisted.
    assert fake_db.rows[db.PROPERTIES_TABLE] == persisted_before
    assert fake_db.rows[db.MATCHES_TABLE] == []


# --------------------------------------------------------------------------- #
# Malformed body -> 422, nothing persisted (Req 10.8)
# --------------------------------------------------------------------------- #


def test_match_missing_required_field_returns_422(fake_db, client):
    body = _property_payload()
    del body["address"]  # required field

    response = client.post("/match", json=body)

    assert response.status_code == 422
    assert fake_db.rows[db.PROPERTIES_TABLE] == []
    assert fake_db.rows[db.MATCHES_TABLE] == []


def test_match_wrong_field_type_returns_422(fake_db, client):
    body = _property_payload(price="not-a-number")

    response = client.post("/match", json=body)

    assert response.status_code == 422
    assert fake_db.rows[db.PROPERTIES_TABLE] == []
    assert fake_db.rows[db.MATCHES_TABLE] == []


def test_match_out_of_vocab_enum_returns_422(fake_db, client):
    body = _property_payload(property_type="castle")

    response = client.post("/match", json=body)

    assert response.status_code == 422
    assert fake_db.rows[db.PROPERTIES_TABLE] == []
    assert fake_db.rows[db.MATCHES_TABLE] == []


def test_match_malformed_json_returns_422(fake_db, client):
    response = client.post(
        "/match",
        content="{not valid json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert fake_db.rows[db.PROPERTIES_TABLE] == []
    assert fake_db.rows[db.MATCHES_TABLE] == []
