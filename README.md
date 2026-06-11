# BuyBox Matcher

Turn messy real estate investor messages into structured **buy boxes**, then
match a property deal against every buyer and rank them with an **explainable
score**.

This is a focused rebuild of the core disposition ("dispo") loop used by
platforms like [Covent](https://getcovent.com) / Dispo Genius: structured buyer
criteria in → ranked, explainable matches out.

> Built as an internship tryout artifact. Demo-first, intentionally scoped to
> the part that matters: matching + AI extraction.

---

## What it does

Two screens, one clear loop.

### 1. Extract
Paste a raw investor message (text or email). AI parses it into a structured
buy box.

```
"Hey, I'm buying SFHs in Tampa and Lakeland, fix and flip, up to about 200k,
 need 3 bed minimum, I pay around 70% of ARV"
```

becomes

```json
{
  "markets": ["Tampa", "Lakeland"],
  "strategy": "fix_and_flip",
  "price_max": 200000,
  "arv_pct_max": 70,
  "property_type": "single_family",
  "min_beds": 3
}
```

### 2. Match
Enter a property deal. The engine scores every saved buyer and returns a ranked
list with a `0-100` score and plain-English reasons.

```
Maria Alvarez — 92/100
  Fit:  Tampa market, fix & flip, price within range, 3+ beds
  Risk: deal at 74% ARV, slightly above her 70% ceiling
```

---

## Why this project

- Sits on the exact core of the dispo business: buyer criteria in, ranked matches out.
- AI-driven, which the target company explicitly expects.
- Not a UI clone — a focused, useful slice.
- Shows AI use, structured data design, matching logic, and product judgment.
- Realistically scoped for 1-2 weeks of solo work.

---

## Tech stack

| Layer    | Choice                                  |
|----------|-----------------------------------------|
| Frontend | React + TypeScript + Tailwind (Vite)    |
| Backend  | FastAPI (Python)                        |
| Database | Supabase (Postgres)                     |
| AI       | OpenAI / Claude API (extraction + reasons) |
| Deploy   | Vercel (web) + Render/Railway (api) + Supabase (db) |

---

## Repo structure

```
buybox-matcher/
├── README.md
├── WRITEUP.md            # tryout writeup: decisions, cuts, next steps
├── docs/
│   ├── architecture.md   # system design + request flow
│   ├── data-model.md     # tables and relationships
│   ├── scoring.md        # the matching algorithm, explained
│   ├── api.md            # endpoint contracts
│   └── roadmap.md        # what's cut and what's next
├── api/                  # FastAPI backend (added during build)
└── web/                  # React frontend (added during build)
```

---

## Getting started

> Scaffolding (api/ and web/) is added in the build phase. This section
> documents the intended setup.

### Prerequisites
- Node 20+
- Python 3.11+
- A Supabase project
- An OpenAI or Anthropic API key

### Backend
```bash
cd api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in SUPABASE_URL, SUPABASE_KEY, AI_API_KEY
uvicorn main:app --reload
```

### Frontend
```bash
cd web
npm install
cp .env.example .env   # fill in VITE_API_URL
npm run dev
```

### Seed data
```bash
cd api
python scripts/seed.py   # inserts ~150 synthetic buyers so Match works instantly
```

---

## Scope

**In:** AI buy box extraction, buyer storage, property input, explainable
matching engine, synthetic seed data, live demo.

**Out (on purpose):** real SMS/email sending, auth/multi-user, real investor
data, full pipeline board. See [docs/roadmap.md](docs/roadmap.md).

---

## Docs

- [Architecture](docs/architecture.md)
- [Data model](docs/data-model.md)
- [Scoring algorithm](docs/scoring.md)
- [API](docs/api.md)
- [Roadmap](docs/roadmap.md)
- [Tryout writeup](WRITEUP.md)

---

## Note on data

All investor/buyer data in this project is **synthetic**. The extraction and
matching engine is data-source agnostic — it works the same against a real
investor database.
