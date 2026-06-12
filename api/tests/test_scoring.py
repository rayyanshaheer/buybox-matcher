"""Scoring_Engine tests — Hypothesis strategies, per-criterion unit tests,
and full-property fixtures (Task 4.1; Req 2.4, 2.9, 3.1, 4.2, 5.5).

This module is the shared home for the entire scoring test suite. Task 4.1
owns the initial creation: the reusable Hypothesis strategies (Section A), one
representative unit test per scoring component (Section B), and the four named
full-property fixtures (Section C).

The later property-based test tasks (4.2-4.13) APPEND their numbered property
tests to the bottom of this file (Section D) and REUSE the module-level
strategies defined in Section A. Keep the strategies module-level and named so
they can be imported/referenced directly, e.g.::

    from api.tests.test_scoring import valid_scoring_properties, valid_scoring_buy_boxes

Reusable strategies defined here (Section A):
  - messy_text(value)              recasing + whitespace-padding wrapper
  - messy_cities()                 city names with case/whitespace noise
  - messy_property_types()         valid property-type values with noise
  - market_lists()                 lists of market strings (may be empty)
  - strategy_values               strategy enum incl. None + out-of-vocab
  - condition_values              condition enum incl. None + out-of-vocab
  - buy_box_property_type_values  property_type incl. None + out-of-vocab
  - price_values / arv_values / arv_pct_max_values
  - beds_values / min_beds_values / baths_values / min_baths_values
  - price_bounds()                 (price_min, price_max): none/single/ordered
  - arv_scenarios()                (price, arv, ceiling) straddling +5.00pp band
  - price_band_scenarios()         (price, price_min, price_max) straddling 10% band
  - valid_scoring_properties()     ScoringProperty with required fields present
  - valid_scoring_buy_boxes()      ScoringBuyBox with markets present
  - scoring_properties_missing_required()  may drop city/property_type (for 4.13)
  - scoring_buy_boxes_missing_required()   may drop markets (for 4.13)
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from api.config import SCORING_CONFIG
from api.models import ScoringBuyBox, ScoringProperty
from api.scoring import ScoringInputError, round_half_up, score

# ===========================================================================
# Section A — Reusable Hypothesis strategies (shared with Tasks 4.2-4.13)
# ===========================================================================

# Vocabularies (mirror api.models enum literals and the seed market set).
STRATEGIES = ["fix_and_flip", "buy_and_hold", "brrrr", "wholesale"]
PROPERTY_TYPES = ["single_family", "multi_family", "condo", "land"]
CONDITIONS = ["distressed", "light_rehab", "turnkey", "any"]
CITIES = [
    "Tampa", "Lakeland", "Orlando", "Dallas",
    "Houston", "Cleveland", "Nashville", "Jacksonville",
]

# Out-of-vocabulary values. NOTE: the engine compares `strategy` and
# `condition` EXACTLY (no normalization), so a recased valid value such as
# "FIX_AND_FLIP" is genuinely out-of-vocab for those two fields. `city` and
# `property_type` ARE normalized (case-insensitive, trimmed), so recased valid
# values still match for those.
OUT_OF_VOCAB_STRATEGY = ["flip", "rental", "FIX_AND_FLIP", "hold", ""]
OUT_OF_VOCAB_CONDITION = ["DISTRESSED", "fixer", "brand_new", ""]
OUT_OF_VOCAB_TYPE = ["duplex", "townhouse", "mobile", ""]

# Half-step bath ladders keep float comparisons clean (no NaN / precision noise).
BATHS_LADDER = [None, 0.0, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]


@st.composite
def messy_text(draw: st.DrawFn, value: str) -> str:
    """Wrap ``value`` with random leading/trailing whitespace and recasing.

    Exercises the case-insensitive, whitespace-trimmed comparison used by the
    Market and Property_Type components (Req 2.5-2.8).
    """
    prefix = draw(st.sampled_from(["", " ", "  ", "\t", " \t "]))
    suffix = draw(st.sampled_from(["", " ", "  ", "\t", " \t "]))
    case = draw(st.sampled_from(["as_is", "upper", "lower", "title", "swap"]))
    if case == "upper":
        value = value.upper()
    elif case == "lower":
        value = value.lower()
    elif case == "title":
        value = value.title()
    elif case == "swap":
        value = value.swapcase()
    return prefix + value + suffix


@st.composite
def messy_cities(draw: st.DrawFn) -> str:
    """A market/city name with case + whitespace noise."""
    return draw(messy_text(draw(st.sampled_from(CITIES))))


@st.composite
def messy_property_types(draw: st.DrawFn) -> str:
    """A valid property-type value with case + whitespace noise."""
    return draw(messy_text(draw(st.sampled_from(PROPERTY_TYPES))))


@st.composite
def market_lists(draw: st.DrawFn) -> list[str]:
    """A list of market strings (possibly empty, possibly with noise)."""
    return draw(st.lists(messy_cities(), min_size=0, max_size=4))


# Enum fields including the null and out-of-vocab edges.
strategy_values = st.one_of(
    st.none(),
    st.sampled_from(STRATEGIES),
    st.sampled_from(OUT_OF_VOCAB_STRATEGY),
)
condition_values = st.one_of(
    st.none(),
    st.sampled_from(CONDITIONS),
    st.sampled_from(OUT_OF_VOCAB_CONDITION),
)
buy_box_property_type_values = st.one_of(
    st.none(),
    messy_property_types(),
    st.sampled_from(OUT_OF_VOCAB_TYPE),
)

# Numeric fields including null / zero edges.
price_values = st.integers(min_value=1, max_value=2_000_000)
arv_values = st.one_of(
    st.none(), st.just(0), st.integers(min_value=10_000, max_value=2_000_000)
)
arv_pct_max_values = st.one_of(st.none(), st.integers(min_value=0, max_value=100))
beds_values = st.one_of(st.none(), st.integers(min_value=0, max_value=8))
min_beds_values = st.one_of(st.none(), st.integers(min_value=0, max_value=6))
baths_values = st.sampled_from(BATHS_LADDER)
min_baths_values = st.sampled_from(BATHS_LADDER)


@st.composite
def price_bounds(draw: st.DrawFn) -> tuple[int | None, int | None]:
    """(price_min, price_max): both-null, single lower, single upper, or ordered pair.

    Covers Req 4.1-4.5 input shapes. When both bounds are present they are
    ordered ``price_min <= price_max`` to mirror the validated model invariant.
    """
    kind = draw(st.sampled_from(["none", "lo_only", "hi_only", "both"]))
    if kind == "none":
        return (None, None)
    if kind == "lo_only":
        return (draw(st.integers(50_000, 600_000)), None)
    if kind == "hi_only":
        return (None, draw(st.integers(50_000, 600_000)))
    a = draw(st.integers(50_000, 600_000))
    b = draw(st.integers(50_000, 600_000))
    return (min(a, b), max(a, b))


@st.composite
def arv_scenarios(draw: st.DrawFn) -> tuple[int, int, int]:
    """(price, arv, arv_pct_max) with Deal_ARV_Pct straddling the +5.00pp band.

    Targets a Deal_ARV_Pct in a window around the ceiling so generated cases
    span under-ceiling (15 pts), slightly-above within 5.00pp (7 pts), and
    well-above (0 pts) — see Req 5.4-5.6.
    """
    ceiling = draw(st.integers(60, 80))
    target_pct = draw(
        st.floats(
            min_value=ceiling - 20.0,
            max_value=ceiling + 15.0,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    arv = draw(st.integers(100_000, 1_000_000))
    price = max(1, round(arv * target_pct / 100))
    return (price, arv, ceiling)


@st.composite
def price_band_scenarios(draw: st.DrawFn) -> tuple[int, int, int]:
    """(price, price_min, price_max) with price straddling the 10% near-band.

    Generates prices around both bounds (inside, within 10% outside, and far
    outside) to exercise the 20/10/0 price bands of Req 4.1-4.3.
    """
    lo = draw(st.integers(80_000, 400_000))
    hi = draw(st.integers(lo, lo + 300_000))
    span = hi - lo if hi > lo else 1
    # A price sampled from below-far .. above-far relative to the bounds.
    price = draw(
        st.integers(
            min_value=max(1, int(lo * 0.7)),
            max_value=int(hi * 1.3) + span,
        )
    )
    return (price, lo, hi)


@st.composite
def valid_scoring_properties(draw: st.DrawFn) -> ScoringProperty:
    """A ScoringProperty with the required scoring fields present (Req 2.10 valid).

    ``city`` and ``property_type`` are always non-null; other fields range over
    their null/zero/edge values.
    """
    return ScoringProperty(
        city=draw(messy_cities()),
        property_type=draw(messy_property_types()),
        condition=draw(condition_values),
        price=draw(price_values),
        arv=draw(arv_values),
        beds=draw(beds_values),
        baths=draw(baths_values),
    )


@st.composite
def valid_scoring_buy_boxes(draw: st.DrawFn) -> ScoringBuyBox:
    """A ScoringBuyBox with ``markets`` present (Req 2.10 valid)."""
    lo, hi = draw(price_bounds())
    return ScoringBuyBox(
        markets=draw(market_lists()),
        strategy=draw(strategy_values),
        property_type=draw(buy_box_property_type_values),
        price_min=lo,
        price_max=hi,
        arv_pct_max=draw(arv_pct_max_values),
        min_beds=draw(min_beds_values),
        min_baths=draw(min_baths_values),
        condition=draw(condition_values),
    )


@st.composite
def scoring_properties_missing_required(draw: st.DrawFn) -> ScoringProperty:
    """A ScoringProperty that may be missing ``city`` and/or ``property_type``.

    For the invalid-input contract tests (Task 4.13 / Req 2.10). At least one
    required field is dropped so the engine must reject the input.
    """
    drop = draw(st.sampled_from(["city", "property_type", "both"]))
    city = None if drop in ("city", "both") else draw(messy_cities())
    ptype = None if drop in ("property_type", "both") else draw(messy_property_types())
    return ScoringProperty(
        city=city,  # type: ignore[arg-type]
        property_type=ptype,  # type: ignore[arg-type]
        condition=draw(condition_values),
        price=draw(price_values),
        arv=draw(arv_values),
        beds=draw(beds_values),
        baths=draw(baths_values),
    )


@st.composite
def scoring_buy_boxes_missing_required(draw: st.DrawFn) -> ScoringBuyBox:
    """A ScoringBuyBox whose ``markets`` is None (invalid for scoring, Req 2.10)."""
    lo, hi = draw(price_bounds())
    return ScoringBuyBox(
        markets=None,  # type: ignore[arg-type]
        strategy=draw(strategy_values),
        property_type=draw(buy_box_property_type_values),
        price_min=lo,
        price_max=hi,
        arv_pct_max=draw(arv_pct_max_values),
        min_beds=draw(min_beds_values),
        min_baths=draw(min_baths_values),
        condition=draw(condition_values),
    )


# ===========================================================================
# Section B — Per-criterion unit tests
# ===========================================================================
#
# A "perfect match" baseline scores exactly 100 (every component full). Each
# unit test overrides one field of the baseline to isolate a single component
# branch, then asserts on the awarded reason and/or resulting score.


def make_property(**overrides) -> ScoringProperty:
    """Baseline property that, with ``make_buy_box``, yields a perfect (100) score."""
    base = dict(
        city="Tampa",
        property_type="single_family",
        condition="distressed",
        price=200_000,
        arv=300_000,  # 200k/300k -> 66.67% ARV
        beds=3,
        baths=2.0,
    )
    base.update(overrides)
    return ScoringProperty(**base)


def make_buy_box(**overrides) -> ScoringBuyBox:
    """Baseline buy box that, with ``make_property``, yields a perfect (100) score."""
    base = dict(
        markets=["Tampa"],
        strategy="fix_and_flip",
        property_type="single_family",
        price_min=100_000,
        price_max=300_000,
        arv_pct_max=70,
        min_beds=3,
        min_baths=2.0,
        condition=None,
    )
    base.update(overrides)
    return ScoringBuyBox(**base)


# --- Market (30) — Req 2.5, 2.6 -------------------------------------------


def test_market_hit_awards_fit_reason():
    result = score(make_property(city="  tAmPa "), make_buy_box(markets=["TAMPA"]))
    assert "operates in   tAmPa " in result.reasons.fit


def test_market_miss_awards_risk_and_caps_score():
    result = score(make_property(city="Miami"), make_buy_box())
    assert "outside their markets" in result.reasons.risk
    # Market component is a hard filter (Req 2.9): total capped at 25.
    assert result.score <= SCORING_CONFIG.hard_filter_cap


# --- Property_Type (10) — Req 2.7, 2.8 ------------------------------------


def test_property_type_hit_awards_fit_reason():
    result = score(
        make_property(property_type="Single_Family"),
        make_buy_box(property_type="single_family"),
    )
    assert "property type Single_Family matches" in result.reasons.fit


def test_property_type_miss_awards_risk_and_caps_score():
    result = score(make_property(), make_buy_box(property_type="condo"))
    assert "property type does not match" in result.reasons.risk
    assert result.score <= SCORING_CONFIG.hard_filter_cap


# --- Strategy (20) — Req 3.1-3.6 ------------------------------------------


def test_strategy_wholesale_fits_any_profile():
    result = score(
        make_property(condition="turnkey"), make_buy_box(strategy="wholesale")
    )
    assert "wholesale fits any deal profile" in result.reasons.fit


def test_strategy_distressed_suits_fix_and_flip():
    result = score(
        make_property(condition="distressed"),
        make_buy_box(strategy="fix_and_flip"),
    )
    assert "distressed deal suits fix_and_flip" in result.reasons.fit


def test_strategy_turnkey_suits_buy_and_hold():
    result = score(
        make_property(condition="turnkey"),
        make_buy_box(strategy="buy_and_hold"),
    )
    assert "turnkey deal suits buy_and_hold" in result.reasons.fit


def test_strategy_mismatch_awards_risk():
    result = score(
        make_property(condition="turnkey"),
        make_buy_box(strategy="fix_and_flip"),
    )
    assert "turnkey deal does not suit fix_and_flip" in result.reasons.risk


def test_strategy_null_strategy_awards_risk():
    result = score(make_property(), make_buy_box(strategy=None))
    assert "buyer strategy could not be determined" in result.reasons.risk


def test_strategy_undeterminable_condition_awards_risk():
    result = score(
        make_property(condition=None), make_buy_box(strategy="fix_and_flip")
    )
    assert "deal profile could not be determined" in result.reasons.risk


# --- Price (20) — Req 4.1-4.5 ---------------------------------------------


def test_price_within_range_awards_fit():
    result = score(
        make_property(price=200_000),
        make_buy_box(price_min=100_000, price_max=300_000),
    )
    assert "price within range" in result.reasons.fit


def test_price_near_upper_bound_awards_partial_risk():
    # 210k is within 10% above the 200k max -> partial credit + risk reason.
    result = score(
        make_property(price=210_000),
        make_buy_box(price_min=100_000, price_max=200_000),
    )
    assert "price near their limit" in result.reasons.risk


def test_price_far_outside_range_awards_risk():
    result = score(
        make_property(price=500_000),
        make_buy_box(price_min=100_000, price_max=200_000),
    )
    assert "price outside range" in result.reasons.risk


def test_price_no_bounds_awards_fit():
    result = score(
        make_property(), make_buy_box(price_min=None, price_max=None)
    )
    assert "no price bound specified" in result.reasons.fit


def test_price_single_lower_bound_satisfied_awards_fit():
    result = score(
        make_property(price=150_000),
        make_buy_box(price_min=100_000, price_max=None),
    )
    assert "price satisfies bound" in result.reasons.fit


# --- ARV % (15) — Req 5.1-5.6 ---------------------------------------------


def test_arv_under_ceiling_awards_fit():
    # 200k/300k = 66.67% <= 70% ceiling.
    result = score(
        make_property(price=200_000, arv=300_000), make_buy_box(arv_pct_max=70)
    )
    assert "at/under 70% ARV ceiling" in result.reasons.fit


def test_arv_slightly_above_ceiling_awards_partial_risk():
    # 148k/200k = 74.0% -> within +5.00pp of 70% ceiling -> 7 points + risk.
    result = score(
        make_property(price=148_000, arv=200_000), make_buy_box(arv_pct_max=70)
    )
    assert "slightly above ARV ceiling (74.0%)" in result.reasons.risk


def test_arv_well_above_ceiling_awards_risk():
    # 200k/200k = 100% -> well above 70% ceiling.
    result = score(
        make_property(price=200_000, arv=200_000), make_buy_box(arv_pct_max=70)
    )
    assert "well above ARV ceiling (100.0%)" in result.reasons.risk


def test_arv_missing_or_zero_awards_risk():
    result = score(make_property(arv=0), make_buy_box(arv_pct_max=70))
    assert "ARV% not evaluable (missing/zero ARV)" in result.reasons.risk


def test_arv_no_ceiling_awards_risk():
    result = score(make_property(), make_buy_box(arv_pct_max=None))
    assert "no ARV ceiling defined" in result.reasons.risk


# --- Beds/Baths (5) — Req 6.1-6.3 -----------------------------------------


def test_beds_baths_met_awards_fit():
    result = score(
        make_property(beds=3, baths=2.0), make_buy_box(min_beds=3, min_baths=2.0)
    )
    assert "meets bed/bath minimums" in result.reasons.fit


def test_beds_baths_below_minimum_awards_risk():
    result = score(make_property(beds=1), make_buy_box(min_beds=4))
    assert "below their bed/bath minimum" in result.reasons.risk


def test_beds_baths_unverifiable_awards_risk():
    result = score(make_property(beds=None), make_buy_box(min_beds=3))
    assert "bed minimum could not be verified" in result.reasons.risk


# ===========================================================================
# Section C — Named full-property fixtures (Req 2.4, 2.9, 4.2, 5.5)
# ===========================================================================


def test_full_property_perfect_match_scores_100():
    """Every component awards its full weight -> score 100, six fit reasons."""
    result = score(make_property(), make_buy_box())
    assert result.score == 100
    # Exactly one reason per component (Req 2.4); all six are fit reasons.
    assert len(result.reasons.fit) == 6
    assert result.reasons.risk == []
    assert all(r for r in result.reasons.fit)


def test_full_property_market_miss_is_capped():
    """A market miss caps the total at the hard-filter cap (Req 2.9)."""
    # All non-market components score full (20+20+15+10+5 = 70) but the market
    # miss forces the cap.
    result = score(make_property(city="Miami"), make_buy_box())
    assert result.score == SCORING_CONFIG.hard_filter_cap  # 25
    assert "outside their markets" in result.reasons.risk
    # Reason accounting still holds: exactly six reasons total (Req 2.4).
    assert len(result.reasons.fit) + len(result.reasons.risk) == 6


def test_full_property_price_edge_awards_partial_and_risk():
    """Price at +10% of the max earns the 10 partial points plus a risk reason (Req 4.2)."""
    # price 330k is exactly 110% of the 300k max -> 10 price points.
    # arv 500k keeps the ARV component full (330k/500k = 66% <= 70%).
    prop = make_property(price=330_000, arv=500_000)
    bb = make_buy_box(price_min=100_000, price_max=300_000, arv_pct_max=70)
    result = score(prop, bb)
    # 30 market + 20 strategy + 10 price + 15 arv + 10 type + 5 beds = 90.
    assert result.score == 90
    assert "price near their limit" in result.reasons.risk


def test_full_property_arv_over_ceiling_awards_partial_and_risk():
    """Deal_ARV_Pct 74% vs a 70% ceiling earns 7 ARV points + 'slightly above' (Req 5.5)."""
    # 148k/200k = 74.0% -> within +5.00pp of 70% -> 7 ARV points.
    prop = make_property(price=148_000, arv=200_000)
    bb = make_buy_box(price_min=100_000, price_max=300_000, arv_pct_max=70)
    result = score(prop, bb)
    # 30 market + 20 strategy + 20 price + 7 arv + 10 type + 5 beds = 92.
    assert result.score == 92
    assert "slightly above ARV ceiling (74.0%)" in result.reasons.risk


# --- round_half_up helper sanity (Req 5.1) --------------------------------


@pytest.mark.parametrize(
    "value,decimals,expected",
    [
        (66.666_666, 2, 66.67),
        (74.005, 2, 74.01),  # exact half rounds away from zero
        (74.0, 2, 74.0),
        (100.0, 2, 100.0),
    ],
)
def test_round_half_up_rounds_away_from_zero(value, decimals, expected):
    assert round_half_up(value, decimals) == expected


# --- Strategy generator sanity check (not a numbered property) -------------
# Confirms the reusable generators in Section A produce inputs the engine can
# score (valid inputs never raise; invalid inputs always raise). The numbered
# correctness properties are added by Tasks 4.2-4.13 in Section D below.


@settings(max_examples=50)
@given(prop=valid_scoring_properties(), bb=valid_scoring_buy_boxes())
def test_generators_produce_scorable_valid_inputs(prop, bb):
    result = score(prop, bb)
    assert 0 <= result.score <= 100
    assert len(result.reasons.fit) + len(result.reasons.risk) == 6


@settings(max_examples=50)
@given(
    prop=scoring_properties_missing_required(),
    bb=valid_scoring_buy_boxes(),
)
def test_generators_produce_rejectable_invalid_inputs(prop, bb):
    with pytest.raises(ScoringInputError):
        score(prop, bb)


# ===========================================================================
# Section D — Numbered correctness properties (appended by Tasks 4.2-4.13)
# ===========================================================================

# Feature: buybox-matcher, Property 1: Scoring determinism
# Validates: Requirements 2.1
#
# The Scoring_Engine is a pure function: given identical Property and Buy_Box
# inputs it must return identical `score` and `reasons` outputs, with no
# dependence on external or mutable state. Calling score() twice on the same
# inputs must produce byte-for-byte identical results.
@settings(max_examples=200)
@given(prop=valid_scoring_properties(), bb=valid_scoring_buy_boxes())
def test_property_1_scoring_determinism(prop, bb):
    first = score(prop, bb)
    second = score(prop, bb)
    assert first.score == second.score
    assert first.reasons.fit == second.reasons.fit
    assert first.reasons.risk == second.reasons.risk


# Feature: buybox-matcher, Property 2: Component scores never exceed configured weights and weights sum to 100
# Validates: Requirements 2.2
#
# The Scoring_Engine reads every weight from a single Scoring_Config whose six
# component weights (Market 30, Strategy 20, Price 20, ARV% 15, Property_Type
# 10, Beds/Baths 5) sum to exactly 100. This property pins that invariant and,
# across the generated input space, asserts that:
#   * each individual component awards between 0 and its configured weight,
#     inclusive (no component ever over-awards), and
#   * the final clamped/capped score stays within [score_min, score_max].
# The per-component bound is checked by reconstructing each component's
# contribution through the engine's own component scorers, so the assertion
# tracks exactly what score() sums internally.
from api.scoring import (  # noqa: E402  (kept with its property block)
    _score_arv,
    _score_beds_baths,
    _score_market,
    _score_price,
    _score_property_type,
    _score_strategy,
)


def test_property_2_configured_weights_sum_to_100():
    """The six component weights sum to exactly 100 (Req 2.2)."""
    cfg = SCORING_CONFIG
    total = (
        cfg.weight_market
        + cfg.weight_strategy
        + cfg.weight_price
        + cfg.weight_arv
        + cfg.weight_property_type
        + cfg.weight_beds_baths
    )
    assert total == 100
    # Pin the individual weights named by Req 2.2.
    assert cfg.weight_market == 30
    assert cfg.weight_strategy == 20
    assert cfg.weight_price == 20
    assert cfg.weight_arv == 15
    assert cfg.weight_property_type == 10
    assert cfg.weight_beds_baths == 5


@settings(max_examples=200)
@given(prop=valid_scoring_properties(), bb=valid_scoring_buy_boxes())
def test_property_2_component_scores_within_configured_weights(prop, bb):
    cfg = SCORING_CONFIG

    # Each component awards between 0 and its configured weight, inclusive.
    component_bounds = [
        (_score_market(prop, bb, cfg), cfg.weight_market),
        (_score_strategy(prop, bb, cfg), cfg.weight_strategy),
        (_score_price(prop, bb, cfg), cfg.weight_price),
        (_score_arv(prop, bb, cfg), cfg.weight_arv),
        (_score_property_type(prop, bb, cfg), cfg.weight_property_type),
        (_score_beds_baths(prop, bb, cfg), cfg.weight_beds_baths),
    ]
    for component, weight in component_bounds:
        assert 0 <= component.points <= weight

    # The summed-then-capped-then-clamped score stays within configured bounds.
    result = score(prop, bb, cfg)
    assert cfg.score_min <= result.score <= cfg.score_max


# Feature: buybox-matcher, Property 3: Score is an integer within [0, 100]
# Validates: Requirements 2.3
#
# The Scoring_Engine returns a `score` that is an integer between 0 and 100
# inclusive. Across the full generated input space (valid properties and buy
# boxes, including null/zero/edge fields), score() must always yield an `int`
# whose value lies within the closed interval [0, 100]. This holds regardless
# of which components fire, whether the hard-filter cap applies, or how the raw
# sum lands before clamping.
@settings(max_examples=200)
@given(prop=valid_scoring_properties(), bb=valid_scoring_buy_boxes())
def test_property_3_score_is_integer_within_0_100(prop, bb):
    result = score(prop, bb)
    assert isinstance(result.score, int)
    assert 0 <= result.score <= 100
