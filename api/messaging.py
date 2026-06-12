"""Message_Drafter stub (design: ``api/messaging.py``; Req 8.1-8.4, 15.1).

This module builds a deterministic first-touch SMS *draft* for a matched buyer.
It is intentionally a stub: it composes text only and performs **zero** outbound
delivery — there is no SMS/email client, no network call, nothing transmitted
(Req 8.3, 15.1). The single public entry point is :func:`draft_message`.

The default implementation is a deterministic template (rather than an AI call)
so the stub works without provider availability while still satisfying the
content contract (Req 8.1): the draft references at least one of the buyer's
``markets`` values and the relevant property's ``address`` or ``city``, and is
between 1 and 480 characters inclusive.
"""

from __future__ import annotations

from typing import Any, Mapping

from api.models import MessageDraft, PropertyInput

#: SMS drafts are capped at 480 characters inclusive (Req 8.1, 8.2).
MAX_SMS_LENGTH = 480


def _first_market(buy_box: Mapping[str, Any]) -> str | None:
    """Return the first non-empty market string from a buy box, else ``None``."""
    markets = buy_box.get("markets") or []
    for market in markets:
        if isinstance(market, str) and market.strip():
            return market.strip()
    return None


def _property_reference(property_in: PropertyInput | None) -> str | None:
    """Return the property's ``address`` (preferred) or ``city`` (Req 8.1).

    Prefers the shorter non-empty value so the combined draft is more likely to
    fit within the 480-character cap without dropping the reference. Either an
    ``address`` or a ``city`` satisfies Req 8.1.
    """
    if property_in is None:
        return None

    candidates = [
        value.strip()
        for value in (property_in.address, property_in.city)
        if isinstance(value, str) and value.strip()
    ]
    if not candidates:
        return None
    # Prefer the shorter reference to maximise the chance it fits within the cap.
    return min(candidates, key=len)


def draft_message(
    buyer: Mapping[str, Any],
    buy_box: Mapping[str, Any],
    property_in: PropertyInput | None = None,
) -> MessageDraft:
    """Build a first-touch SMS draft for ``buyer`` (Req 8.1, 8.2, 8.3).

    The draft is a deterministic template that references at least one of the
    buyer's ``markets`` values and (when a property is supplied) the property's
    ``address`` or ``city`` (Req 8.1). It is never transmitted (Req 8.3, 15.1);
    this function returns the text only.

    Returns a :class:`~api.models.MessageDraft` with ``channel="sms"`` and a
    non-empty ``text`` of length 1..480 (Req 8.2). The text is composed to keep
    the market and property references near the start and is truncated only as a
    final guard so it never exceeds the cap.
    """
    name = (buyer.get("name") or "").strip() or "there"
    market = _first_market(buy_box)
    prop_ref = _property_reference(property_in)

    if market and prop_ref:
        text = (
            f"Hi {name}, I've got a deal at {prop_ref} that looks like a fit for "
            f"your {market} buy box. Want the details? (Draft preview — not sent.)"
        )
    elif prop_ref:
        text = (
            f"Hi {name}, I've got a deal at {prop_ref} that may fit your buy box. "
            f"Want the details? (Draft preview — not sent.)"
        )
    elif market:
        text = (
            f"Hi {name}, I've got a new deal that looks like a fit for your "
            f"{market} buy box. Want the details? (Draft preview — not sent.)"
        )
    else:
        text = (
            f"Hi {name}, I've got a new deal that may fit your buy box. "
            f"Want the details? (Draft preview — not sent.)"
        )

    # Final guard: never exceed the SMS cap (Req 8.1, 8.2). The cap is comfortably
    # above the template length for typical inputs; truncation is a last resort.
    if len(text) > MAX_SMS_LENGTH:
        text = text[:MAX_SMS_LENGTH]

    return MessageDraft(channel="sms", text=text)
