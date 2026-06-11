"""Pure Match_Service result-processing helpers (design: "Match_Service").

This module holds the side-effect-free pieces of the Match orchestration that
shape a scored result set before it is returned by ``POST /match``. They are
deliberately separated from the route/orchestration code in ``api/main.py`` so
they can be exercised in isolation by property-based tests (tasks 5.2, 5.3)
without standing up the FastAPI app or a database.

The two responsibilities here, taken straight from the requirements:

* **Ordering (Req 7.3).** Matches are ordered by ``score`` descending, and ties
  on ``score`` are broken by ``buyer_id`` ascending. The sort is stable, so the
  ``(score desc, buyer_id asc)`` ordering is total and deterministic.

* **Filter-then-limit (Req 7.6, 7.7).** A ``min_score`` filter is applied
  **strictly before** any ``limit`` truncation: every retained match satisfies
  ``score >= min_score`` first, and only then are at most ``limit`` matches
  kept. Applying the filter before the cap is what keeps a low ``limit`` from
  hiding qualifying matches behind disqualified ones.

Every function is **pure**: it reads only its arguments, performs no I/O, and
never mutates the input sequence (a new list is always returned). The helpers
operate on "match-like" items, meaning either a mapping with ``"score"`` /
``"buyer_id"`` keys (e.g. a dict) or an object exposing ``score`` /
``buyer_id`` attributes (e.g. :class:`api.models.MatchItem`).
"""

from __future__ import annotations

from typing import Any, TypeVar

__all__ = [
    "get_score",
    "get_buyer_id",
    "sort_matches",
    "filter_by_min_score",
    "apply_limit",
    "order_and_limit",
]

# A match-like item: a mapping with "score"/"buyer_id" keys, or an object with
# ``score``/``buyer_id`` attributes. Kept generic so callers get their own type
# back from the ordering/filtering helpers.
MatchT = TypeVar("MatchT")


def get_score(match: Any) -> int:
    """Read the ``score`` from a match-like item.

    Supports both mappings (``match["score"]``) and attribute-bearing objects
    (``match.score``) so the helpers work for dicts and
    :class:`api.models.MatchItem` alike.
    """
    if isinstance(match, dict):
        return match["score"]
    return match.score


def get_buyer_id(match: Any) -> Any:
    """Read the ``buyer_id`` from a match-like item.

    Supports both mappings (``match["buyer_id"]``) and attribute-bearing
    objects (``match.buyer_id``). ``buyer_id`` values are compared with their
    natural ordering (string uuids sort lexicographically) for the tie-break.
    """
    if isinstance(match, dict):
        return match["buyer_id"]
    return match.buyer_id


def sort_matches(matches: list[MatchT]) -> list[MatchT]:
    """Return matches ordered by ``score`` desc, then ``buyer_id`` asc (Req 7.3).

    The input list is not mutated; a new ordered list is returned. The ordering
    is total and deterministic: ties on ``score`` are broken by ``buyer_id`` in
    ascending order.
    """
    # Sort ascending by buyer_id first, then a stable sort by descending score.
    # Because Python's sort is stable, the ascending buyer_id order is preserved
    # within each equal-score group, yielding (score desc, buyer_id asc).
    by_buyer = sorted(matches, key=get_buyer_id)
    return sorted(by_buyer, key=get_score, reverse=True)


def filter_by_min_score(
    matches: list[MatchT], min_score: int | None
) -> list[MatchT]:
    """Keep only matches whose ``score >= min_score`` (Req 7.6).

    When ``min_score`` is ``None`` the list is returned unchanged (no filter
    requested). The input list is never mutated.
    """
    if min_score is None:
        return list(matches)
    return [m for m in matches if get_score(m) >= min_score]


def apply_limit(matches: list[MatchT], limit: int | None) -> list[MatchT]:
    """Return at most ``limit`` matches from the front of the list (Req 7.7).

    When ``limit`` is ``None`` the list is returned unchanged (no cap
    requested). The input list is never mutated.
    """
    if limit is None:
        return list(matches)
    return list(matches[:limit])


def order_and_limit(
    matches: list[MatchT],
    min_score: int | None = None,
    limit: int | None = None,
) -> list[MatchT]:
    """Sort, then filter by ``min_score``, then truncate to ``limit``.

    The composed pipeline used by the Match_Service: order by ``score`` desc /
    ``buyer_id`` asc (Req 7.3), apply the ``min_score`` filter **before** the
    ``limit`` cap (Req 7.6, 7.7), and return a new list. The sort and filter are
    order-independent on the retained set, but the filter is always applied
    before truncation so a small ``limit`` never hides qualifying matches.
    """
    ordered = sort_matches(matches)
    filtered = filter_by_min_score(ordered, min_score)
    return apply_limit(filtered, limit)
