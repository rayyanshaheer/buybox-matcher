"""Match_Service helper tests — property-based tests for the pure
filter-then-limit result-shaping helpers in ``api/matching.py``.

The helpers under test (``sort_matches``, ``filter_by_min_score``,
``apply_limit``, ``order_and_limit``) are side-effect-free and operate on
"match-like" items. These tests exercise them with Hypothesis-generated match
sets, ``min_score`` filters, and ``limit`` caps, covering the named Correctness
Properties from the design.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from api.matching import (
    apply_limit,
    filter_by_min_score,
    get_buyer_id,
    get_score,
    order_and_limit,
    sort_matches,
)

# ---------------------------------------------------------------------------
# Strategies — generate match-like dicts with a `score` (0..100) and a unique
# `buyer_id` (string uuid-ish). Uniqueness on buyer_id mirrors the real domain
# (one match row per buyer) and makes the (score desc, buyer_id asc) ordering a
# total order, so the expected-pipeline comparison is unambiguous.
# ---------------------------------------------------------------------------

scores = st.integers(min_value=0, max_value=100)
buyer_ids = st.text(
    alphabet="abcdef0123456789-", min_size=1, max_size=12
)


@st.composite
def match_lists(draw: st.DrawFn) -> list[dict]:
    """A list of match-like dicts with distinct ``buyer_id`` values."""
    ids = draw(
        st.lists(buyer_ids, min_size=0, max_size=25, unique=True)
    )
    return [
        {"buyer_id": bid, "score": draw(scores)} for bid in ids
    ]


# min_score / limit query-parameter strategies. ``None`` models "param not
# provided"; the integer ranges mirror the validated API surface (min_score
# 0..100, limit >= 1) plus a few values above the list size to exercise the
# "limit larger than result set" path.
min_scores = st.one_of(st.none(), st.integers(min_value=0, max_value=100))
limits = st.one_of(st.none(), st.integers(min_value=1, max_value=30))


def _expected(matches, min_score, limit):
    """Reference implementation: sort -> filter -> truncate."""
    ordered = sorted(
        sorted(matches, key=get_buyer_id),
        key=get_score,
        reverse=True,
    )
    if min_score is not None:
        ordered = [m for m in ordered if get_score(m) >= min_score]
    if limit is not None:
        ordered = ordered[:limit]
    return ordered


# ===========================================================================
# Feature: buybox-matcher, Property 14: Filter-then-limit retrieval
# ===========================================================================
# Validates: Requirements 7.6, 7.7
#
# Req 7.6: when a `min_score` is provided, only matches with score >= min_score
#          are returned, and this filter is applied BEFORE any `limit`.
# Req 7.7: when a `limit` is provided, at most `limit` matches are returned,
#          selected after sorting and after the `min_score` filter.
#
# The property asserts the three guarantees together: every returned item
# satisfies score >= min_score, the returned count never exceeds limit, and the
# whole result equals the reference sort -> filter -> truncate pipeline. The
# last clause is what pins down the ORDER of operations: filtering strictly
# before truncation, so a small limit can never hide qualifying matches behind
# disqualified ones.
@settings(max_examples=200)
@given(matches=match_lists(), min_score=min_scores, limit=limits)
def test_property_14_filter_then_limit_retrieval(matches, min_score, limit):
    original = list(matches)
    result = order_and_limit(matches, min_score, limit)

    # Every retained result clears the min_score floor (Req 7.6).
    if min_score is not None:
        assert all(get_score(m) >= min_score for m in result)

    # The result never exceeds the limit cap (Req 7.7).
    if limit is not None:
        assert len(result) <= limit

    # The result is exactly sort -> filter -> truncate, in that order
    # (filter strictly before limit: Req 7.6 before 7.7).
    assert result == _expected(matches, min_score, limit)

    # Purity: the helper must not mutate its input sequence.
    assert matches == original


@settings(max_examples=200)
@given(matches=match_lists(), min_score=st.integers(min_value=0, max_value=100))
def test_property_14_filter_before_limit_does_not_hide_qualifiers(
    matches, min_score
):
    """Filtering before limiting: with limit=1, the single returned match (if
    any) is a top-scoring match that clears min_score — never a disqualified one
    surfaced because it sorted ahead (Req 7.6 applied before 7.7)."""
    result = order_and_limit(matches, min_score=min_score, limit=1)
    qualifying = [m for m in matches if get_score(m) >= min_score]

    if qualifying:
        assert len(result) == 1
        top = result[0]
        assert get_score(top) >= min_score
        # It is a highest-scoring qualifying match.
        assert get_score(top) == max(get_score(m) for m in qualifying)
    else:
        assert result == []


@settings(max_examples=200)
@given(matches=match_lists(), min_score=min_scores, limit=limits)
def test_property_14_pipeline_matches_composed_helpers(
    matches, min_score, limit
):
    """``order_and_limit`` equals the explicit composition of the individual
    sort/filter/limit helpers (Req 7.6, 7.7)."""
    composed = apply_limit(
        filter_by_min_score(sort_matches(matches), min_score), limit
    )
    assert order_and_limit(matches, min_score, limit) == composed
