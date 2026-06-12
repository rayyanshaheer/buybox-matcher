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

## 🔗 Live Demo

| | Link |
|---|---|
| **App** | [buybox-matcher.vercel.app](https://buybox-matcher.vercel.app) |
| **API** | [buybox-matcher.onrender.com](https://buybox-matcher.onrender.com/health) |
| **Video walkthrough** | [Loom](https://www.loom.com/share/70f5a2f479c045c3aab5c7cebe3c83c4) |

> Note: The API runs on Render's free tier and sleeps after 15 min of inactivity. The first request after waking up takes ~30s.

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

All commands below are run from the repository root unless noted otherwise.

### Prerequisites
- Node 20+
- Python 3.11+
- A Supabase project (or any Postgres database)
- An OpenAI or Anthropic API key

### Secret-handling boundary

Keys live on the **backend only**. The AI provider keys (`OPENAI_API_KEY` /
`ANTHROPIC_API_KEY`) and the database credentials (`SUPABASE_URL`,
`SUPABASE_KEY`) are read exclusively from the API's environment and are never
exposed to the browser. The frontend's only configured external reference is
`VITE_API_URL` — it holds no provider or database secrets (Req 14.2, 14.3).
Copy each `.env.example` to a local `.env` and never commit the populated file.

### Backend setup

1. Create and activate a virtual environment, then install dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r api/requirements.txt
   ```

2. Configure the environment. Copy the example file and fill in real values
   (`AI_PROVIDER`, the matching provider key, `SUPABASE_URL`, `SUPABASE_KEY`,
   and `ALLOWED_ORIGIN`):

   ```bash
   cp api/.env.example api/.env
   ```

3. Apply the database schema. Run the migration `api/migrations/0001_init.sql`
   against your database. The simplest path is to paste its contents into the
   Supabase SQL editor (SQL → New query) and run it there.

   To apply it from the command line with `psql`, use your Postgres connection
   string — found in the Supabase dashboard under **Project Settings →
   Database → Connection string**. Note this is the `postgresql://...`
   connection string, which is different from `SUPABASE_URL` (the HTTPS REST
   endpoint used by the app):

   ```bash
   psql "postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres" \
     -f api/migrations/0001_init.sql
   ```

4. Run the API (the app is `api.main:app`):

   ```bash
   uvicorn api.main:app --reload
   ```

   The API serves at `http://localhost:8000` by default; check
   `GET /health` for a liveness probe.

### Seed data

Populate the database with synthetic buyers so the Match flow works on first
run. The seed script inserts **140-160 synthetic buyers**, each with one buy
box, covering every strategy and property type (Req 11.1). It is idempotent —
reruns do not create duplicates:

```bash
python -m api.scripts.seed
```

### Frontend setup

1. Configure the environment. Copy the example file and set `VITE_API_URL` to
   point at the running backend (e.g. `http://localhost:8000`):

   ```bash
   cp web/.env.example web/.env
   ```

2. Install dependencies and run the dev server:

   ```bash
   cd web
   npm install
   npm run dev
   ```

   The dev server runs at `http://localhost:5173` by default. Make sure this
   origin matches the backend's `ALLOWED_ORIGIN`.

3. Production build and tests:

   ```bash
   npm run build     # type-check + production bundle
   npm test          # Vitest unit + property tests
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
