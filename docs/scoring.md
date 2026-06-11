# Scoring Algorithm

The match score answers one question: **how well does this property fit this
buyer's buy box?** Output is `0-100` plus the reasons behind it.

The core is a **weighted, rule-based scorer**. It is deterministic and
inspectable on purpose — every point is traceable to a rule.

## Why rule-based first

- **Explainable.** A wholesaler trusts "Tampa market ✓, price in range ✓" more
  than an opaque number.
- **No training data yet.** A learned model needs labelled outcomes
  (which buyer actually bought). We don't have that on day one.
- **Easy to tune.** Weights live in one place and are simple to adjust.

The roadmap covers moving to a learned model once closed-deal outcomes exist.

## Criteria and weights

| Criterion        | Weight | How it scores                                              |
|------------------|--------|------------------------------------------------------------|
| Market match     | 30     | Full if property city ∈ buyer markets, else 0              |
| Strategy fit     | 20     | Full if the deal's profile suits the buyer's strategy      |
| Price in range   | 20     | Full inside range; partial near edges; 0 far outside       |
| ARV % fit        | 15     | Full if deal ARV% ≤ buyer ceiling; decays as it exceeds    |
| Property type    | 10     | Full on exact type match, else 0                           |
| Beds/baths min   | 5      | Full if minimums met, else 0                               |

Total possible: **100**.

## Hard filters vs soft scoring

Two criteria act as **hard filters** — if they fail badly, the buyer is not a
real match regardless of other points:

- **Market**: if the property city is not in the buyer's markets, cap the score
  low (markets are rarely flexible).
- **Property type**: a land buyer will not take a single-family home.

Everything else is **soft** — it reduces the score and produces a "risk" reason
rather than disqualifying.

## Scoring detail

### Market (30)
```
city in buy_box.markets        → 30, fit:  "operates in {city}"
else                           → 0,  risk: "outside their markets"
```

### Strategy fit (20)
Maps the deal's condition/profile to suitable strategies.
```
distressed/light_rehab  → suits fix_and_flip, brrrr
turnkey                 → suits buy_and_hold
any deal                → suits wholesale
match → 20, fit; mismatch → 0, risk
```

### Price in range (20)
```
price_min ≤ price ≤ price_max          → 20, fit:  "price within range"
within 10% of a bound                  → 10, risk: "price near their limit"
further outside                        → 0,  risk: "price outside range"
```

### ARV % fit (15)
```
deal_arv_pct = price / arv * 100
deal_arv_pct ≤ arv_pct_max             → 15, fit:  "at/under their ARV ceiling"
≤ ceiling + 5                          → 7,  risk: "slightly above ARV ceiling"
else                                   → 0,  risk: "well above ARV ceiling"
```

### Property type (10)
```
property_type == buy_box.property_type → 10, fit
else                                   → 0,  risk: "different property type"
```

### Beds/baths minimum (5)
```
beds ≥ min_beds and baths ≥ min_baths  → 5, fit
else                                   → 0, risk: "below their bed/bath minimum"
```

## Output shape

```json
{
  "buyer_id": "…",
  "score": 92,
  "reasons": {
    "fit":  ["Tampa market", "fix & flip", "price within range", "3+ beds"],
    "risk": ["deal at 74% ARV, above their 70% ceiling"]
  }
}
```

## Tunability

All weights and thresholds live in a single `scoring_config` object so they can
be changed without touching logic. This also makes the eventual swap to learned
weights a drop-in.

## Testing

The scorer is a pure function: `score(property, buy_box) -> {score, reasons}`.
Unit tests cover each criterion in isolation plus a few full-property fixtures
(perfect match, market miss, price edge, ARV over ceiling).
