"""Message_Drafter tests — Property 17: message draft content invariant.

The Message_Drafter (``api/messaging.py``) builds a deterministic first-touch
SMS *draft* for a matched buyer. Per Req 8.1 the draft must reference at least
one of the buyer's ``markets`` values and the relevant property's ``address``
or ``city``, with a length between 1 and 480 characters inclusive.

This module owns the property-based test for that content invariant
(Property 17 in the design). The Hypothesis strategies below intelligently
constrain to the realistic input space — short, human-readable market names,
addresses, and cities (the kind of values extraction/seed data produce) — so
the market and property references comfortably fit within the 480-character
SMS cap rather than colliding with the final truncation guard.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from api.messaging import MAX_SMS_LENGTH, draft_message
from api.models import MessageDraft, PropertyInput

PROPERTY_TYPES = ["single_family", "multi_family", "condo", "land"]
CONDITIONS = ["distressed", "light_rehab", "turnkey", "any"]


# A non-whitespace, human-readable token (letters/digits/spaces) of modest
# length. ``min_size`` guards against whitespace-only values collapsing to an
# empty reference under ``str.strip()``.
def _readable_text(min_size: int, max_size: int) -> st.SearchStrategy[str]:
    return (
        st.text(
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"),
                whitelist_characters=" .",
            ),
            min_size=min_size,
            max_size=max_size,
        )
        # Keep at least one non-whitespace character so the stripped value is
        # a meaningful reference (markets/address/city are never blank here).
        .map(lambda s: s.strip())
        .filter(lambda s: len(s) >= 1)
    )


@st.composite
def buyers(draw: st.DrawFn) -> dict:
    """A buyer mapping with an optional human name (as the route supplies)."""
    name = draw(st.one_of(st.none(), _readable_text(1, 40)))
    return {"name": name}


@st.composite
def buy_boxes_with_market(draw: st.DrawFn) -> dict:
    """A buy box whose ``markets`` has at least one non-empty entry (Req 8.1)."""
    markets = draw(
        st.lists(_readable_text(1, 30), min_size=1, max_size=4)
    )
    return {"markets": markets}


@st.composite
def properties(draw: st.DrawFn) -> PropertyInput:
    """A PropertyInput with non-empty ``address`` and ``city`` (Req 8.1)."""
    return PropertyInput(
        address=draw(_readable_text(1, 60)),
        city=draw(_readable_text(1, 40)),
        price=draw(st.integers(min_value=1, max_value=2_000_000)),
        arv=draw(st.integers(min_value=1, max_value=2_000_000)),
        beds=draw(st.one_of(st.none(), st.integers(min_value=0, max_value=8))),
        baths=draw(st.one_of(st.none(), st.floats(min_value=0, max_value=6))),
        property_type=draw(st.sampled_from(PROPERTY_TYPES)),
        condition=draw(st.sampled_from(CONDITIONS)),
    )


# Feature: buybox-matcher, Property 17: Message draft content invariant
# Validates: Requirements 8.1
#
# For any Buyer with at least one `markets` entry and any associated Property,
# the generated draft text references at least one of the buyer's markets and
# the property's `address` or `city`, and its length is between 1 and 480
# characters inclusive.
@settings(max_examples=200)
@given(buyer=buyers(), buy_box=buy_boxes_with_market(), property_in=properties())
def test_property_17_message_draft_content_invariant(buyer, buy_box, property_in):
    draft = draft_message(buyer, buy_box, property_in)

    # Channel + type contract (Req 8.2).
    assert isinstance(draft, MessageDraft)
    assert draft.channel == "sms"

    # Length is within [1, 480] inclusive (Req 8.1).
    assert 1 <= len(draft.text) <= MAX_SMS_LENGTH

    # References at least one of the buyer's markets (Req 8.1).
    stripped_markets = [m.strip() for m in buy_box["markets"] if m.strip()]
    assert any(market in draft.text for market in stripped_markets)

    # References the property's address or city (Req 8.1).
    address = property_in.address.strip()
    city = property_in.city.strip()
    assert (address and address in draft.text) or (city and city in draft.text)
