"""Seed verification tests (Req 11.1, 11.2, 11.4, 11.5).

These tests exercise both halves of ``api/scripts/seed.py``:

* the pure :func:`generate_seed_buyers` generator — verifying count, the
  exactly-one buy_box shape, strategy/property-type coverage (Req 11.4),
  allowed markets (Req 11.4), and the numeric value ranges (Req 11.5); and
* the persistence :func:`run_seed` — verifying a run inserts 140-160 buyers
  each with one buy_box (Req 11.1), and that a rerun is idempotent: the count
  stays in range with no duplicate buyers and no extra buy_boxes (Req 11.2).

An injected in-memory fake Supabase client (mirroring ``test_db.py``) is used so
the tests run without the ``supabase`` package or live credentials.
"""

import pytest

from api import db
from api.scripts import seed


# --------------------------------------------------------------------------- #
# In-memory fake Supabase client (same shape as test_db.py)
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
    def __init__(self, db_: "_FakeClient", name: str):
        self._db = db_
        self._name = name

    def insert(self, payload):
        return _FakeQuery(self, "insert").insert(payload)

    def select(self, columns):
        return _FakeQuery(self, "select").select(columns)

    def delete(self):
        return _FakeQuery(self, "delete").delete()

    def run(self, op, payload, filters):
        if op == "insert":
            return self._db.handle_insert(self._name, payload)
        if op == "select":
            return self._db.handle_select(self._name)
        if op == "delete":
            return self._db.handle_delete(self._name, filters)
        raise AssertionError(f"unexpected op {op}")


class _FakeClient:
    """Minimal in-memory fake of the Supabase client used by api.db."""

    def __init__(self):
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
        # Emulate the on-delete-cascade FK: deleting a buyer removes its buy_boxes.
        if name == db.BUYERS_TABLE:
            removed_ids = {r.get("id") for r in removed}
            self.rows[db.BUY_BOXES_TABLE] = [
                bb
                for bb in self.rows[db.BUY_BOXES_TABLE]
                if bb.get("buyer_id") not in removed_ids
            ]
        return _Response(removed)


@pytest.fixture
def client():
    return _FakeClient()


# --------------------------------------------------------------------------- #
# Shared range/vocabulary assertion helper (Req 11.4, 11.5)
# --------------------------------------------------------------------------- #


def _assert_buy_box_valid(bb: dict) -> None:
    # markets subset of the allowed set, non-empty (Req 11.4).
    assert bb["markets"], "markets must be non-empty"
    assert set(bb["markets"]).issubset(set(seed.ALLOWED_MARKETS))
    assert len(set(bb["markets"])) == len(bb["markets"]), "markets must be distinct"

    # enums (Req 11.4, 11.5).
    assert bb["strategy"] in seed.STRATEGIES
    assert bb["property_type"] in seed.PROPERTY_TYPES
    assert bb["condition"] in seed.CONDITIONS

    # price range (Req 11.5).
    assert seed.PRICE_FLOOR <= bb["price_min"] <= seed.PRICE_CEILING
    assert seed.PRICE_FLOOR <= bb["price_max"] <= seed.PRICE_CEILING
    assert bb["price_min"] <= bb["price_max"]

    # arv_pct_max (Req 11.5).
    assert seed.ARV_PCT_MIN <= bb["arv_pct_max"] <= seed.ARV_PCT_MAX

    # beds / baths (Req 11.5).
    assert seed.MIN_BEDS_FLOOR <= bb["min_beds"] <= seed.MIN_BEDS_CEILING
    assert seed.MIN_BATHS_FLOOR <= bb["min_baths"] <= seed.MIN_BATHS_CEILING

    # non-empty synthetic raw_text (Req 11.5).
    assert isinstance(bb["raw_text"], str)
    assert bb["raw_text"].strip()


# --------------------------------------------------------------------------- #
# Pure generator: generate_seed_buyers (Req 11.1, 11.4, 11.5)
# --------------------------------------------------------------------------- #


def test_default_count_is_within_range():
    buyers = seed.generate_seed_buyers()
    assert seed.MIN_SEED_COUNT <= len(buyers) <= seed.MAX_SEED_COUNT


@pytest.mark.parametrize("count", [140, 150, 160])
def test_each_buyer_has_exactly_one_buy_box(count):
    buyers = seed.generate_seed_buyers(count)
    assert len(buyers) == count
    for buyer in buyers:
        assert "buy_box" in buyer
        assert isinstance(buyer["buy_box"], dict)


def test_generated_buy_boxes_obey_ranges_and_vocab():
    for buyer in seed.generate_seed_buyers(160):
        _assert_buy_box_valid(buyer["buy_box"])


def test_all_strategies_and_property_types_represented():
    buyers = seed.generate_seed_buyers(140)
    strategies = {b["buy_box"]["strategy"] for b in buyers}
    types = {b["buy_box"]["property_type"] for b in buyers}
    assert set(seed.STRATEGIES).issubset(strategies)
    assert set(seed.PROPERTY_TYPES).issubset(types)


def test_generation_is_deterministic_for_same_seed():
    assert seed.generate_seed_buyers(140, seed=7) == seed.generate_seed_buyers(
        140, seed=7
    )


@pytest.mark.parametrize("count", [0, 139, 161, 500])
def test_count_outside_band_is_rejected(count):
    with pytest.raises(ValueError):
        seed.generate_seed_buyers(count)


def test_emails_are_unique():
    buyers = seed.generate_seed_buyers(160)
    emails = [b["email"] for b in buyers]
    assert len(set(emails)) == len(emails)


# --------------------------------------------------------------------------- #
# Persistence: run_seed (Req 11.1, 11.2)
# --------------------------------------------------------------------------- #


def test_run_seed_inserts_buyers_each_with_one_buy_box(client):
    summary = seed.run_seed(client=client)
    assert summary["inserted"] == summary["generated"]

    buyers = db.list_buyers_with_buy_boxes(client=client)
    assert seed.MIN_SEED_COUNT <= len(buyers) <= seed.MAX_SEED_COUNT
    # exactly one buy_box per buyer (Req 11.1).
    assert len(client.rows[db.BUY_BOXES_TABLE]) == len(buyers)
    for buyer in buyers:
        assert buyer["buy_box"] is not None
        _assert_buy_box_valid(buyer["buy_box"])


def test_rerun_is_idempotent_no_duplicates_and_count_in_range(client):
    seed.run_seed(client=client)
    first_count = len(client.rows[db.BUYERS_TABLE])
    first_emails = sorted(b["email"] for b in client.rows[db.BUYERS_TABLE])

    summary = seed.run_seed(client=client)

    second_count = len(client.rows[db.BUYERS_TABLE])
    second_emails = sorted(b["email"] for b in client.rows[db.BUYERS_TABLE])

    # The rerun cleared the prior synthetic set before reinserting (Req 11.2).
    assert summary["deleted"] == first_count
    assert summary["mode"] == "cleared_and_reinserted"

    # Count stays in range and does not grow (Req 11.2).
    assert second_count == first_count
    assert seed.MIN_SEED_COUNT <= second_count <= seed.MAX_SEED_COUNT

    # No duplicate buyer records: emails remain unique and buy_boxes 1:1.
    assert len(set(second_emails)) == len(second_emails)
    assert second_emails == first_emails
    assert len(client.rows[db.BUY_BOXES_TABLE]) == second_count


def test_rerun_does_not_remove_non_synthetic_buyers(client):
    # A real (non-synthetic) buyer must survive a seed rerun (Req 11.2).
    db.insert_buyer_with_buy_box(
        name="Real Investor",
        company="Genuine Capital",
        email="real.investor@genuine.com",
        buy_box={
            "markets": ["Tampa"],
            "strategy": "wholesale",
            "property_type": "single_family",
            "price_min": 100_000,
            "price_max": 200_000,
            "arv_pct_max": 70,
            "min_beds": 3,
            "min_baths": 2.0,
            "condition": "any",
            "raw_text": "real buyer note",
        },
        client=client,
    )

    seed.run_seed(client=client)
    seed.run_seed(client=client)

    emails = [b["email"] for b in client.rows[db.BUYERS_TABLE]]
    assert "real.investor@genuine.com" in emails
    # Synthetic buyers stay within their band, plus the single real buyer.
    synthetic = [e for e in emails if e.endswith(f"@{seed.SEED_EMAIL_DOMAIN}")]
    assert seed.MIN_SEED_COUNT <= len(synthetic) <= seed.MAX_SEED_COUNT


def test_persisted_buy_box_markets_subset_of_allowed(client):
    seed.run_seed(client=client)
    for bb in client.rows[db.BUY_BOXES_TABLE]:
        assert set(bb["markets"]).issubset(set(seed.ALLOWED_MARKETS))
