"""Unit tests for api.db (Req 9.1, 9.2, 9.3, 9.4, 9.5, 9.7, 9.8).

These tests use an injected fake Supabase client (a minimal query-builder
stand-in), so they require neither the ``supabase`` package nor live
credentials — exercising the lazy/injectable client design.
"""

import pytest

from api import db


# --------------------------------------------------------------------------- #
# Fake Supabase client / query builder
# --------------------------------------------------------------------------- #


class _ApiError(Exception):
    """Stand-in for postgrest.exceptions.APIError exposing a ``code``."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


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
    def __init__(self, db: "_FakeClient", name: str):
        self._db = db
        self._name = name

    # query-builder entry points -------------------------------------------- #
    def insert(self, payload):
        return _FakeQuery(self, "insert").insert(payload)

    def select(self, columns):
        return _FakeQuery(self, "select").select(columns)

    def delete(self):
        return _FakeQuery(self, "delete").delete()

    # execution -------------------------------------------------------------- #
    def run(self, op, payload, filters):
        self._db.calls.append((self._name, op, payload, filters))
        if op == "insert":
            return self._db.handle_insert(self._name, payload)
        if op == "select":
            return self._db.handle_select(self._name)
        if op == "delete":
            return self._db.handle_delete(self._name, filters)
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
        # Inject an error to raise on the next insert into a given table.
        self.raise_on_insert: dict[str, Exception] = {}

    def table(self, name):
        return _FakeTable(self, name)

    def _gen_id(self, prefix):
        self._next_id += 1
        return f"{prefix}-{self._next_id}"

    def handle_insert(self, name, payload):
        if name in self.raise_on_insert:
            raise self.raise_on_insert[name]
        row = dict(payload)
        row.setdefault("id", self._gen_id(name[:-1]))
        self.rows[name].append(row)
        return _Response([row])

    def handle_select(self, name):
        if name == db.BUYERS_TABLE:
            # emulate PostgREST embedding of buy_boxes
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
        kept = []
        removed = []
        for row in self.rows[name]:
            if all(row.get(col) == val for col, val in filters):
                removed.append(row)
            else:
                kept.append(row)
        self.rows[name] = kept
        return _Response(removed)


@pytest.fixture
def client():
    return _FakeClient()


def _valid_buy_box():
    return {
        "markets": ["Tampa", "Orlando"],
        "strategy": "fix_and_flip",
        "property_type": "single_family",
        "price_min": 100_000,
        "price_max": 200_000,
        "arv_pct_max": 70,
        "min_beds": 3,
        "min_baths": 2.0,
        "condition": "distressed",
        "raw_text": "looking for distressed SFH in Tampa under 200k",
    }


def _valid_property():
    return {
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


# --------------------------------------------------------------------------- #
# insert_buyer_with_buy_box (Req 9.1, 9.2, 9.7)
# --------------------------------------------------------------------------- #


def test_insert_buyer_with_buy_box_persists_both(client):
    result = db.insert_buyer_with_buy_box(
        name="Jane Investor",
        company="Acme Capital",
        buy_box=_valid_buy_box(),
        client=client,
    )
    assert result["buyer_id"]
    assert result["buy_box"]["buyer_id"] == result["buyer_id"]
    assert len(client.rows[db.BUYERS_TABLE]) == 1
    assert len(client.rows[db.BUY_BOXES_TABLE]) == 1
    # raw_text is persisted on the buy box (required column).
    assert client.rows[db.BUY_BOXES_TABLE][0]["raw_text"]


def test_insert_buyer_only_sends_known_buy_box_fields(client):
    bb = _valid_buy_box()
    bb["unexpected"] = "ignored"
    db.insert_buyer_with_buy_box(name="X", buy_box=bb, client=client)
    stored = client.rows[db.BUY_BOXES_TABLE][0]
    assert "unexpected" not in stored


def test_insert_buyer_rejects_invalid_strategy_without_persisting(client):
    bb = _valid_buy_box()
    bb["strategy"] = "flipping"  # not in vocabulary
    with pytest.raises(db.EnumViolationError):
        db.insert_buyer_with_buy_box(name="X", buy_box=bb, client=client)
    # Nothing persisted — the buyer insert never ran.
    assert client.rows[db.BUYERS_TABLE] == []
    assert client.rows[db.BUY_BOXES_TABLE] == []


def test_insert_buyer_allows_null_enums(client):
    bb = _valid_buy_box()
    bb["strategy"] = None
    bb["property_type"] = None
    bb["condition"] = None
    db.insert_buyer_with_buy_box(name="X", buy_box=bb, client=client)
    assert len(client.rows[db.BUY_BOXES_TABLE]) == 1


def test_insert_buyer_unique_violation_rolls_back_buyer(client):
    # Simulate the 1:1 unique constraint firing on the buy_box insert.
    client.raise_on_insert[db.BUY_BOXES_TABLE] = _ApiError("23505", "duplicate key")
    with pytest.raises(db.UniqueViolationError):
        db.insert_buyer_with_buy_box(name="X", buy_box=_valid_buy_box(), client=client)
    # The orphaned buyer must have been rolled back (Req 9.7 - nothing persisted).
    assert client.rows[db.BUYERS_TABLE] == []
    assert client.rows[db.BUY_BOXES_TABLE] == []


# --------------------------------------------------------------------------- #
# list_buyers_with_buy_boxes (Req 9.2)
# --------------------------------------------------------------------------- #


def test_list_buyers_empty_returns_empty_list(client):
    assert db.list_buyers_with_buy_boxes(client=client) == []


def test_list_buyers_embeds_single_buy_box(client):
    db.insert_buyer_with_buy_box(name="A", buy_box=_valid_buy_box(), client=client)
    db.insert_buyer_with_buy_box(name="B", buy_box=_valid_buy_box(), client=client)
    buyers = db.list_buyers_with_buy_boxes(client=client)
    assert len(buyers) == 2
    for b in buyers:
        assert b["buy_box"] is not None
        assert b["buy_box"]["buyer_id"] == b["id"]
        # embedding key normalised away
        assert db.BUY_BOXES_TABLE not in b


# --------------------------------------------------------------------------- #
# insert_property (Req 9.3, 9.5, 9.6)
# --------------------------------------------------------------------------- #


def test_insert_property_persists_row(client):
    row = db.insert_property(_valid_property(), client=client)
    assert row["id"]
    assert row["city"] == "Tampa"
    assert len(client.rows[db.PROPERTIES_TABLE]) == 1


def test_insert_property_never_writes_deal_arv_pct(client):
    prop = _valid_property()
    prop["deal_arv_pct"] = 68.18  # must be dropped (Req 9.6)
    db.insert_property(prop, client=client)
    assert "deal_arv_pct" not in client.rows[db.PROPERTIES_TABLE][0]


def test_insert_property_rejects_invalid_condition(client):
    prop = _valid_property()
    prop["condition"] = "fixer"
    with pytest.raises(db.EnumViolationError):
        db.insert_property(prop, client=client)
    assert client.rows[db.PROPERTIES_TABLE] == []


# --------------------------------------------------------------------------- #
# insert_match (Req 9.4, 9.8)
# --------------------------------------------------------------------------- #


def test_insert_match_persists_row(client):
    row = db.insert_match(
        property_id="prop-1",
        buyer_id="buyer-1",
        score=87,
        reasons={"fit": ["operates in Tampa"], "risk": []},
        client=client,
    )
    assert row["id"]
    assert row["score"] == 87
    assert row["reasons"]["fit"] == ["operates in Tampa"]


def test_insert_match_fk_violation_surfaced(client):
    client.raise_on_insert[db.MATCHES_TABLE] = _ApiError(
        "23503", "violates foreign key constraint"
    )
    with pytest.raises(db.ForeignKeyViolationError):
        db.insert_match(
            property_id="missing",
            buyer_id="missing",
            score=10,
            reasons={"fit": [], "risk": ["x"]},
            client=client,
        )
    assert client.rows[db.MATCHES_TABLE] == []


# --------------------------------------------------------------------------- #
# Error translation (Req 9.5, 9.7, 9.8)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "code,expected",
    [
        ("23505", db.UniqueViolationError),
        ("23503", db.ForeignKeyViolationError),
        ("23514", db.EnumViolationError),
    ],
)
def test_translate_by_sqlstate_code(code, expected):
    translated = db._translate_db_exception(_ApiError(code))
    assert isinstance(translated, expected)


@pytest.mark.parametrize(
    "message,expected",
    [
        ("duplicate key value violates unique constraint", db.UniqueViolationError),
        ("insert violates foreign key constraint", db.ForeignKeyViolationError),
        ("new row violates check constraint ck_strategy", db.EnumViolationError),
    ],
)
def test_translate_by_message_fallback(message, expected):
    translated = db._translate_db_exception(Exception(message))
    assert isinstance(translated, expected)


def test_translate_unknown_returns_none():
    assert db._translate_db_exception(Exception("some other failure")) is None


def test_unknown_db_error_propagates_unchanged(client):
    client.raise_on_insert[db.PROPERTIES_TABLE] = RuntimeError("network down")
    with pytest.raises(RuntimeError, match="network down"):
        db.insert_property(_valid_property(), client=client)


# --------------------------------------------------------------------------- #
# Lazy / injectable client (testability)
# --------------------------------------------------------------------------- #


def test_set_and_reset_client():
    fake = _FakeClient()
    db.set_client(fake)
    try:
        assert db.get_client() is fake
    finally:
        db.reset_client()
    assert db._client is None
