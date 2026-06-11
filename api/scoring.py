"""The pure, deterministic Scoring_Engine (design: "Scoring_Engine").

``score(property, buy_box, config) -> ScoreResult`` computes a 0..100 match
score and the fit/risk reasons that produced it. The function is **pure**:
given identical inputs it returns identical outputs, performs no I/O, and never
mutates its inputs (Req 2.1). Every weight and threshold is read from the
injected :class:`api.config.ScoringConfig` (Req 2.2).

The engine computes six independent component scores — Market (30), Strategy
(20), Price (20), ARV% (15), Property_Type (10), Beds/Baths (5) — sums them,
then applies the hard-filter cap: when the Market or Property_Type component
scores 0 the total is capped at ``config.hard_filter_cap`` (Req 2.9). The final
score is clamped into ``[score_min, score_max]`` (Req 2.3). Each component
contributes **exactly one** reason, to ``fit`` if its full weight was awarded
as a fit and to ``risk`` otherwise, so ``len(fit) + len(risk) == 6`` (Req 2.4).

Before scoring, the invalid-input contract (Req 2.10) is enforced: if
``property`` or ``buy_box`` is null, or a field required for scoring
(``property.city``, ``property.property_type``, ``buy_box.markets``) is
missing, the engine raises :class:`ScoringInputError` without producing a
numeric score and without mutating its inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from api.config import SCORING_CONFIG, ScoringConfig
from api.models import Reasons, ScoreResult, ScoringBuyBox, ScoringProperty

__all__ = ["score", "ScoringInputError", "round_half_up"]


class ScoringInputError(ValueError):
    """Raised when scoring inputs are null or missing a required field.

    Signals the invalid-input contract (Req 2.10): the engine returns no
    numeric score and leaves the inputs unmodified. The message identifies the
    missing or invalid input.
    """


# --------------------------------------------------------------------------- #
# Internal component result. Each of the six components yields exactly one of
# these: the points it awarded plus a single fit-or-risk reason (Req 2.4).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Component:
    points: int
    is_fit: bool
    reason: str


def _norm(value: str) -> str:
    """Case-insensitive, leading/trailing-whitespace-trimmed normalization."""
    return value.strip().casefold()


def round_half_up(value: float, decimals: int) -> float:
    """Round ``value`` to ``decimals`` places using round-half-up (Req 5.1).

    Uses :class:`decimal.Decimal` with ``ROUND_HALF_UP`` so that exact halves
    round away from zero, avoiding banker's-rounding surprises.
    """
    quantum = Decimal(1).scaleb(-decimals)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- #
# Components
# --------------------------------------------------------------------------- #


def _score_market(
    property: ScoringProperty, buy_box: ScoringBuyBox, config: ScoringConfig
) -> _Component:
    """Market component (weight 30) — Req 2.5, 2.6.

    Case-insensitive, whitespace-trimmed comparison of the property ``city``
    against each ``markets`` entry.
    """
    city_norm = _norm(property.city)
    market_norms = {_norm(m) for m in buy_box.markets if m is not None}
    if city_norm in market_norms:
        return _Component(
            config.weight_market, True, f"operates in {property.city}"
        )
    return _Component(0, False, "outside their markets")


def _score_property_type(
    property: ScoringProperty, buy_box: ScoringBuyBox, config: ScoringConfig
) -> _Component:
    """Property_Type component (weight 10) — Req 2.7, 2.8.

    Same normalization as Market. This is the second hard-filter component.
    """
    if (
        buy_box.property_type is not None
        and _norm(property.property_type) == _norm(buy_box.property_type)
    ):
        return _Component(
            config.weight_property_type,
            True,
            f"property type {property.property_type} matches",
        )
    return _Component(0, False, "property type does not match")


def _score_strategy(
    property: ScoringProperty, buy_box: ScoringBuyBox, config: ScoringConfig
) -> _Component:
    """Strategy component (weight 20) — Req 3.1-3.6.

    Evaluation order matters: an invalid/null strategy is rejected first, then
    ``wholesale`` is awarded before the condition-validity guard so 3.3 holds
    for any property regardless of its ``condition``.
    """
    valid_strategies = {"fix_and_flip", "brrrr", "buy_and_hold", "wholesale"}
    valid_conditions = {"distressed", "light_rehab", "turnkey"}

    strategy = buy_box.strategy
    condition = property.condition

    # 3.6 — invalid/null strategy.
    if strategy is None or strategy not in valid_strategies:
        return _Component(0, False, "buyer strategy could not be determined")

    # 3.3 — wholesale fits any deal profile (checked before condition guard).
    if strategy == "wholesale" and config.wholesale_fits_any:
        return _Component(
            config.weight_strategy, True, "wholesale fits any deal profile"
        )

    # 3.5 — invalid/null condition (for non-wholesale strategies).
    if condition is None or condition not in valid_conditions:
        return _Component(0, False, "deal profile could not be determined")

    # 3.1, 3.2 — condition is suited to the strategy.
    if strategy in config.suitable_strategies(condition):
        return _Component(
            config.weight_strategy, True, f"{condition} deal suits {strategy}"
        )

    # 3.4 — condition is a known profile but not suited to the strategy.
    return _Component(0, False, f"{condition} deal does not suit {strategy}")


def _score_price(
    property: ScoringProperty, buy_box: ScoringBuyBox, config: ScoringConfig
) -> _Component:
    """Price component (weight 20) — Req 4.1-4.5.

    Full credit in range / no-bound; partial credit within ``price_near_band_pct``
    of a violated bound; zero beyond that.
    """
    lo = buy_box.price_min
    hi = buy_box.price_max
    p = property.price
    band = config.price_near_band_pct
    partial = config.price_partial_points
    full = config.weight_price

    # 4.5 — neither bound specified.
    if lo is None and hi is None:
        return _Component(full, True, "no price bound specified")

    # Defensive: a null property price cannot be evaluated against a bound.
    if p is None:
        return _Component(0, False, "price could not be evaluated")

    # 4.1-4.3 — both bounds present.
    if lo is not None and hi is not None:
        if lo <= p <= hi:
            return _Component(full, True, "price within range")
        if (lo * (1 - band) <= p < lo) or (hi < p <= hi * (1 + band)):
            return _Component(partial, False, "price near their limit")
        return _Component(0, False, "price outside range")

    # 4.4 — exactly one bound present.
    if lo is not None:  # single lower bound
        if p >= lo:
            return _Component(full, True, "price satisfies bound")
        if lo * (1 - band) <= p < lo:
            return _Component(partial, False, "price near their limit")
        return _Component(0, False, "price outside range")

    # single upper bound (hi is not None)
    if p <= hi:
        return _Component(full, True, "price satisfies bound")
    if hi < p <= hi * (1 + band):
        return _Component(partial, False, "price near their limit")
    return _Component(0, False, "price outside range")


def _score_arv(
    property: ScoringProperty, buy_box: ScoringBuyBox, config: ScoringConfig
) -> _Component:
    """ARV% component (weight 15) — Req 5.1-5.6.

    Deal_ARV_Pct is computed at match time as ``round_half_up(price/arv*100, 2)``
    only when ``arv`` is present and non-zero and a ceiling is defined.
    """
    # 5.2 — missing/zero ARV (or a null price) cannot be evaluated.
    if property.arv is None or property.arv == 0 or property.price is None:
        return _Component(
            0, False, "ARV% not evaluable (missing/zero ARV)"
        )

    # 5.3 — no ceiling defined for the buyer.
    if buy_box.arv_pct_max is None:
        return _Component(0, False, "no ARV ceiling defined")

    # 5.1 — compute Deal_ARV_Pct (round half up to configured decimals).
    deal_pct = round_half_up(
        property.price / property.arv * 100, config.arv_round_decimals
    )
    ceiling = buy_box.arv_pct_max

    # 5.4 — at or under the ceiling.
    if deal_pct <= ceiling:
        return _Component(
            config.weight_arv, True, f"at/under {ceiling}% ARV ceiling"
        )
    # 5.5 — slightly above (within the near band).
    if deal_pct <= ceiling + config.arv_near_band_pp:
        return _Component(
            config.arv_partial_points,
            False,
            f"slightly above ARV ceiling ({deal_pct}%)",
        )
    # 5.6 — well above the ceiling.
    return _Component(0, False, f"well above ARV ceiling ({deal_pct}%)")


def _score_beds_baths(
    property: ScoringProperty, buy_box: ScoringBuyBox, config: ScoringConfig
) -> _Component:
    """Beds/Baths component (weight 5) — Req 6.1-6.3."""
    min_beds = buy_box.min_beds
    min_baths = buy_box.min_baths
    beds = property.beds
    baths = property.baths

    beds_ok = min_beds is None or (beds is not None and beds >= min_beds)
    baths_ok = min_baths is None or (baths is not None and baths >= min_baths)

    # 6.3 — a minimum is set but the property value is missing.
    if min_beds is not None and beds is None:
        return _Component(0, False, "bed minimum could not be verified")
    if min_baths is not None and baths is None:
        return _Component(0, False, "bath minimum could not be verified")

    # 6.1 — every applicable minimum is met.
    if beds_ok and baths_ok:
        return _Component(
            config.weight_beds_baths, True, "meets bed/bath minimums"
        )

    # 6.2 — below a minimum.
    return _Component(0, False, "below their bed/bath minimum")


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def _validate_inputs(
    property: ScoringProperty | None, buy_box: ScoringBuyBox | None
) -> None:
    """Enforce the invalid-input contract (Req 2.10).

    Raises :class:`ScoringInputError` identifying the missing/invalid input.
    Performs no mutation.
    """
    missing: list[str] = []
    if property is None:
        missing.append("property")
    if buy_box is None:
        missing.append("buy_box")
    if not missing:
        if getattr(property, "city", None) is None:
            missing.append("property.city")
        if getattr(property, "property_type", None) is None:
            missing.append("property.property_type")
        if getattr(buy_box, "markets", None) is None:
            missing.append("buy_box.markets")
    if missing:
        raise ScoringInputError(
            "Cannot score: null or missing required input(s): "
            + ", ".join(missing)
        )


def score(
    property: ScoringProperty,
    buy_box: ScoringBuyBox,
    config: ScoringConfig = SCORING_CONFIG,
) -> ScoreResult:
    """Score a property against a buy box (design: "Scoring_Engine"; Req 2.x-6.x).

    Pure and side-effect-free: identical inputs yield identical outputs, no I/O
    is performed, and the inputs are not mutated (Req 2.1, 2.10).

    Raises:
        ScoringInputError: if ``property``/``buy_box`` is null or a required
            scoring field (``city``, ``property_type``, ``markets``) is missing.
    """
    _validate_inputs(property, buy_box)

    # Six independent components, in reason-ordering sequence.
    market = _score_market(property, buy_box, config)
    strategy = _score_strategy(property, buy_box, config)
    price = _score_price(property, buy_box, config)
    arv = _score_arv(property, buy_box, config)
    property_type = _score_property_type(property, buy_box, config)
    beds_baths = _score_beds_baths(property, buy_box, config)

    components = (market, strategy, price, arv, property_type, beds_baths)

    raw = sum(c.points for c in components)

    # Hard-filter cap (Req 2.9): Market or Property_Type scoring 0 caps total.
    if market.points == 0 or property_type.points == 0:
        final = min(raw, config.hard_filter_cap)
    else:
        final = raw

    # Clamp into [score_min, score_max] (Req 2.3).
    final = max(config.score_min, min(final, config.score_max))

    # Exactly one reason per component (Req 2.4).
    fit: list[str] = [c.reason for c in components if c.is_fit]
    risk: list[str] = [c.reason for c in components if not c.is_fit]

    return ScoreResult(score=int(final), reasons=Reasons(fit=fit, risk=risk))
