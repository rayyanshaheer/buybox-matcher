# API

Base URL: `${API_URL}` (e.g. `http://localhost:8000` in dev).
All bodies are JSON. No auth in the tryout build.

---

## POST /buy-boxes/extract

Extract a structured buy box from a raw investor message and save the buyer.

**Request**
```json
{
  "raw_text": "Buying SFHs in Tampa and Lakeland, fix and flip, up to 200k, 3 bed min, 70% of ARV",
  "name": "Maria Alvarez",
  "company": "Bayshore Equity"
}
```

**Response `201`**
```json
{
  "buyer_id": "8f3a…",
  "buy_box": {
    "markets": ["Tampa", "Lakeland"],
    "strategy": "fix_and_flip",
    "property_type": "single_family",
    "price_min": null,
    "price_max": 200000,
    "arv_pct_max": 70,
    "min_beds": 3,
    "min_baths": null,
    "condition": "distressed"
  }
}
```

**Errors**
- `422` — message could not be parsed into a usable buy box.

---

## GET /buyers

List saved buyers with their buy boxes.

**Response `200`**
```json
[
  {
    "buyer_id": "8f3a…",
    "name": "Maria Alvarez",
    "company": "Bayshore Equity",
    "buy_box": { "markets": ["Tampa"], "strategy": "fix_and_flip", "…": "…" }
  }
]
```

---

## POST /match

Score a property against all saved buyers and return a ranked list.

**Request**
```json
{
  "address": "3012 W San Carlos St",
  "city": "Tampa",
  "price": 148000,
  "arv": 200000,
  "beds": 3,
  "baths": 2,
  "property_type": "single_family",
  "condition": "distressed"
}
```

**Response `200`**
```json
{
  "property_id": "a1b2…",
  "matches": [
    {
      "buyer_id": "8f3a…",
      "name": "Maria Alvarez",
      "score": 92,
      "reasons": {
        "fit":  ["Tampa market", "fix & flip", "price within range", "3+ beds"],
        "risk": ["deal at 74% ARV, above their 70% ceiling"]
      }
    }
  ]
}
```

Results are sorted by `score` descending.

**Query params**
- `min_score` (int, optional) — only return buyers at/above this score.
- `limit` (int, optional) — cap the number of buyers returned.

---

## POST /match/{buyer_id}/message  *(stub)*

Generate a personalized first-touch message for a matched buyer. Returns the
draft text only — **no message is actually sent** in the tryout build.

**Response `200`**
```json
{
  "channel": "sms",
  "text": "Hey Maria, it's Rayyan. Saw Bayshore's flips around Tampa — I've got a 3/2 fixer on W San Carlos at a 74% ARV basis. Want the details?"
}
```

---

## GET /health

Liveness check.

**Response `200`**
```json
{ "status": "ok" }
```
