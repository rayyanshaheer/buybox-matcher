# Architecture

## Overview

BuyBox Matcher is a small two-tier app: a React frontend, a FastAPI backend,
and Postgres (via Supabase). AI is called server-side for buy box extraction
and for generating human-readable match reasons.

```
┌──────────────┐      HTTPS / JSON      ┌──────────────┐
│   React web  │  ───────────────────▶  │  FastAPI api │
│  (Vite + TS) │  ◀───────────────────  │   (Python)   │
└──────────────┘                        └──────┬───────┘
                                               │
                          ┌────────────────────┼────────────────────┐
                          ▼                                          ▼
                  ┌──────────────┐                          ┌──────────────┐
                  │   Supabase   │                          │   AI API     │
                  │  (Postgres)  │                          │ (OpenAI/Claude)│
                  └──────────────┘                          └──────────────┘
```

## Why this shape

- **Server-side AI calls.** API keys never touch the browser. The frontend
  only talks to our backend.
- **FastAPI for the core.** The matching engine and extraction are Python — fast
  to write, easy to test, and the natural home if scoring moves to a learned
  model later.
- **Supabase for data.** Managed Postgres with a clean client. No infra overhead
  for a tryout, and it scales to a real workload.
- **Stateless API.** No sessions. Each request carries what it needs. Easy to
  deploy and horizontally scale.

## Request flows

### Extract a buy box
```
User pastes message
  → POST /buy-boxes/extract { raw_text }
  → API calls AI with a strict extraction prompt + JSON schema
  → API validates the parsed fields (types, ranges, enums)
  → API stores buyer + buy_box in Postgres
  → returns structured buy box to the UI
```

### Match a property
```
User submits a property
  → POST /match { property }
  → API loads all buy boxes
  → scoring engine computes score + reasons per buyer (pure function)
  → API sorts by score, returns ranked list
  → (optional) AI rewrites the reasons into a natural sentence
```

## Design principles

- **Explainability over magic.** Every score ships with the reasons that
  produced it. No black box.
- **Pure scoring core.** The scoring function takes a property and a buy box and
  returns a number plus reasons. No I/O inside it, so it is trivially testable.
- **AI at the edges.** AI handles fuzzy text (extraction, phrasing). The match
  decision itself is deterministic and inspectable.
- **Synthetic but realistic.** Seed data mirrors real buy box shapes so the demo
  behaves like production.

## Deployment

| Component | Host             | Notes                              |
|-----------|------------------|------------------------------------|
| web       | Vercel           | static build, `VITE_API_URL` env   |
| api       | Render / Railway | container or buildpack, env vars   |
| db        | Supabase         | Postgres + connection string       |

Environment variables are documented in each package's `.env.example`.
