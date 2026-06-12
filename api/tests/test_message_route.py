"""Unit tests for the message-draft route ``POST /match/{buyer_id}/message``.

Covers (Req 8.2, 8.3, 8.4, 10.5, 10.6, 15.1):

* the 200 success shape ``{channel: "sms", text}`` for an existing buyer,
* the 404 path for an unknown ``buyer_id`` with **no draft generated**, and
* the invariant that the route never invokes an outbound messaging client —
  the drafter composes text only and nothing is transmitted (Req 8.3, 15.1).

The route reads the buyer through the module-level :mod:`api.db` helpers, which
resolve the shared (injectable) Supabase client. These tests inject a minimal
in-memory fake via ``db.set_client`` (the same testability seam exercised by
``test_db.py``), so they need neither the ``supabase`` package nor live
credentials.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.main as main
from api import db, messaging


# --------------------------------------------------------------------------- #
# Minimal in-memory fake Supabase client
#
# Only the query path used by ``db.get_buyer_with_buy_box`` is implemented:
#   client.table(BUYERS_TABLE).select("*, buy_boxes(*)").eq("id", buyer_id).execute()
# The fake embeds each buyer's single buy_box under the ``buy_boxes`` key exactly
# as PostgREST does, so the helper's normalisation runs against realistic shapes.
# --------------------------------------------------------------------------- #


class _Response:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, table: "_FakeTable"):
        self._table = table
        self._filters: list[tuple[str, object]] = []

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def execute(self):
        rows = self._table.rows
        for column, value in self._filters:
            rows = [r for r in rows if str(r.get(column)) == str(value)]
        return _Response(rows)


class _FakeTable:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def select(self, columns):
        return _FakeQuery(self).select(columns)


class _FakeClient:
    """In-memory fake exposing only what the message route needs."""

    def __init__(self, buyers: list[dict] | None = None):
        self._buyers = buyers or []

    def table(self, name):
        if name == db.BUYERS_TABLE:
            return _FakeTable(self._buyers)
        # The message route only ever reads the buyers table (with embedded
        # buy_boxes). Any other table access would be unexpected.
        raise AssertionError(f"unexpected table access: {name}")


def _buyer_row(buyer_id: str = "buyer-1") -> dict:
    """A buyer row with an embedded buy_box, shaped like a PostgREST result."""
    return {
        "id": buyer_id,
        "name": "Jane Investor",
        "company": "Acme Capital",
        db.BUY_BOXES_TABLE: [
            {
                "buyer_id": buyer_id,
                "markets": ["Tampa", "Orlando"],
                "strategy": "fix_and_flip",
                "property_type": "single_family",
                "price_min": 100_000,
                "price_max": 200_000,
                "arv_pct_max": 70,
                "min_beds": 3,
                "min_baths": 2.0,
                "condition": "distressed",
                "raw_text": "distressed SFH in Tampa under 200k",
            }
        ],
    }


@pytest.fixture
def client():
    """TestClient with an injected fake db client holding one known buyer."""
    db.set_client(_FakeClient(buyers=[_buyer_row("buyer-1")]))
    try:
        yield TestClient(main.app)
    finally:
        db.reset_client()


# --------------------------------------------------------------------------- #
# 200 success shape (Req 8.2, 10.5)
# --------------------------------------------------------------------------- #


def test_existing_buyer_returns_200_sms_draft_shape(client):
    response = client.post("/match/buyer-1/message")

    assert response.status_code == 200
    body = response.json()
    # Exactly the documented shape: a "sms" channel and a non-empty text.
    assert body["channel"] == "sms"
    assert isinstance(body["text"], str)
    assert 1 <= len(body["text"]) <= 480


def test_existing_buyer_draft_references_a_market(client):
    # Req 8.1 content contract: the draft references one of the buyer's markets.
    response = client.post("/match/buyer-1/message")
    assert response.status_code == 200
    text = response.json()["text"]
    assert "Tampa" in text or "Orlando" in text


def test_existing_buyer_with_property_body_references_property(client):
    # When a property body is supplied the draft references its address/city.
    response = client.post(
        "/match/buyer-1/message",
        json={
            "address": "123 Main St",
            "city": "Tampa",
            "price": 150_000,
            "arv": 220_000,
            "beds": 3,
            "baths": 2.0,
            "property_type": "single_family",
            "condition": "distressed",
        },
    )
    assert response.status_code == 200
    text = response.json()["text"]
    assert "123 Main St" in text or "Tampa" in text


# --------------------------------------------------------------------------- #
# 404 unknown buyer — drafter NOT invoked (Req 8.4, 10.6)
# --------------------------------------------------------------------------- #


def test_unknown_buyer_returns_404(client):
    response = client.post("/match/does-not-exist/message")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_unknown_buyer_does_not_invoke_drafter(client, monkeypatch):
    """An unknown buyer must 404 *before* the drafter runs (Req 8.4)."""
    calls: list[tuple] = []
    real_draft_message = messaging.draft_message

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real_draft_message(*args, **kwargs)

    # The route imports draft_message into its own namespace, so patch there.
    monkeypatch.setattr(main, "draft_message", spy)

    response = client.post("/match/does-not-exist/message")

    assert response.status_code == 404
    assert calls == []  # drafter was never invoked (no draft generated)


def test_existing_buyer_does_invoke_drafter_once(client, monkeypatch):
    """Sanity counterpart: an existing buyer invokes the drafter exactly once."""
    calls: list[tuple] = []
    real_draft_message = messaging.draft_message

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real_draft_message(*args, **kwargs)

    monkeypatch.setattr(main, "draft_message", spy)

    response = client.post("/match/buyer-1/message")

    assert response.status_code == 200
    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# No outbound messaging client is invoked (Req 8.3, 15.1)
# --------------------------------------------------------------------------- #


def test_messaging_module_exposes_no_outbound_client():
    """The drafter is a stub: it must expose no send/transmit/deliver surface.

    Req 8.3 / 15.1 require the draft text only — nothing is ever transmitted.
    There is therefore no outbound messaging client to invoke. Assert the
    module surface contains no callable whose name implies delivery, so a future
    accidental transmit path would fail this test.
    """
    forbidden = ("send", "transmit", "deliver", "dispatch", "publish")
    for attr in dir(messaging):
        lowered = attr.lower()
        assert not any(
            token in lowered for token in forbidden
        ), f"unexpected outbound-looking symbol in api.messaging: {attr}"


def test_draft_route_makes_no_outbound_call(client, monkeypatch):
    """Guard: a successful draft must not reach out over the network.

    Any attempt by the route/drafter to open a socket would trip this guard,
    proving the stub composes text only (Req 8.3, 15.1).
    """
    import socket

    def _blocked(*args, **kwargs):
        raise AssertionError("the draft route must not make any outbound connection")

    monkeypatch.setattr(socket.socket, "connect", _blocked)

    response = client.post("/match/buyer-1/message")

    assert response.status_code == 200
    assert response.json()["channel"] == "sms"
