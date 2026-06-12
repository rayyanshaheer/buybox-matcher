# Implementation Plan: BuyBox Matcher

## Overview

This plan converts the BuyBox Matcher design into incremental coding steps. It follows the recommended build order: database schema first, then the backend skeleton, then the pure Scoring_Engine with its property-based tests right behind it, then the Match orchestration, AI extraction, seed data, the message stub, and finally the React frontend and polish. Each step builds on prior ones and ends by wiring new code into the running app.

The backend is FastAPI / Python 3.11+ (`api/`); the frontend is React + TypeScript + Vite + Tailwind (`web/`); persistence is Supabase / Postgres. Backend property tests use Hypothesis; frontend property tests use Vitest + fast-check. Every property-based test is tagged with a `# Feature: buybox-matcher, Property N: ...` comment and runs at >= 100 iterations.

## Tasks

- [x] 1. Database schema and migration
  - [x] 1.1 Author SQL DDL for the four tables and indexes
    - Create `api/migrations/0001_init.sql` with `buyers`, `buy_boxes`, `properties`, and `matches` tables exactly as specified in the design "Postgres Schema (SQL DDL)" section
    - Include `gen_random_uuid()` PK defaults, `created_at timestamptz default now()` on all tables, `buy_boxes.uq_buy_box_buyer` unique constraint (1:1), `ck_price_range`, and `ck_strategy`/`ck_property_type`/`ck_condition` enum check constraints, plus `arv_pct_max between 0 and 100`
    - Add FK constraints on `matches.property_id` and `matches.buyer_id`, omit any `deal_arv_pct` column on `properties`, and create `idx_matches_property` and `idx_buy_boxes_buyer`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8_

- [x] 2. Backend skeleton: config, models, db client, app
  - [x] 2.1 Set up backend project structure and dependencies
    - Create the `api/` package layout (`api/__init__.py`, `api/main.py`, `api/config.py`, `api/models.py`, `api/db.py`, `api/scripts/`, `api/tests/`)
    - Create `api/requirements.txt` with pinned versions for `fastapi`, `uvicorn`, `pydantic`, `supabase`, `hypothesis`, `pytest`, and the AI provider SDK(s)
    - _Requirements: 14.3_

  - [x] 2.2 Implement config.py with env loading, startup validation, and Scoring_Config
    - Read `AI_PROVIDER`, the selected provider key (`OPENAI_API_KEY`/`ANTHROPIC_API_KEY`), `SUPABASE_URL`, `SUPABASE_KEY`, and `ALLOWED_ORIGIN` from the environment
    - On startup, validate every required credential is present and non-empty; if one is missing, halt AI-dependent startup and emit an error naming the variable without printing its value
    - Define the `ScoringConfig` dataclass and `SCORING_CONFIG` constant with weights Market 30, Strategy 20, Price 20, ARV 15, Property_Type 10, Beds/Baths 5, plus the partial-credit and ARV band thresholds
    - _Requirements: 2.2, 14.3, 14.4_

  - [x] 2.3 Implement Pydantic models in models.py
    - Define `Strategy`, `PropertyType`, `Condition` literals; `ExtractRequest` (with the not-whitespace `raw_text` validator), `BuyBoxModel` (with the `price_min <= price_max` model validator and `arv_pct_max` range), `ExtractResponse`, `PropertyInput`, `MatchReasons`, `MatchItem`, `MatchResponse`, and `MessageDraft`
    - Define internal frozen dataclasses `PropertyInput`/`BuyBoxInput`, `ScoreResult`, `Reasons` used by the Scoring_Engine
    - _Requirements: 1.2, 1.8, 1.10, 9.5_

  - [x] 2.4 Implement db.py Supabase client and typed query helpers
    - Construct the Supabase client from config and add insert/select helpers for the four tables (insert buyer+buy_box, list buyers with buy_boxes, insert property, insert match)
    - Surface enum-check, unique (1:1), and FK violations as explicit errors without persisting
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.7, 9.8_

  - [x] 2.5 Create FastAPI app with /health and CORS
    - In `api/main.py` build the FastAPI app, register `GET /health` returning `{"status":"ok"}`, and configure `CORSMiddleware` with `allow_origins=[ALLOWED_ORIGIN]`
    - _Requirements: 10.7, 10.9, 10.10_

  - [x] 2.6 Write integration tests for /health and CORS
    - Assert `GET /health` returns 200 `{"status":"ok"}`; assert the `Access-Control-Allow-Origin` header is present for a matching `Origin` and omitted otherwise
    - _Requirements: 10.7, 10.9, 10.10_

- [x] 3. Scoring engine (pure function)
  - [x] 3.1 Implement scoring.py score() with all six components, cap, and invalid-input contract
    - Implement `score(property, buy_box, config=SCORING_CONFIG) -> ScoreResult` as a pure, side-effect-free, no-I/O function in `api/scoring.py`
    - Implement Market (30, case-insensitive trimmed), Property_Type (10, case-insensitive trimmed), Strategy (20, strategy-mapping with wholesale checked before condition guard), Price (20, in-range/partial-credit/out bands incl. single-bound and both-null), ARV% (15, `round_half_up` computation, null/zero ARV and null ceiling handling, slightly-above vs well-above bands), and Beds/Baths (5, null-minimum and unverifiable handling)
    - Sum components, apply the hard-filter cap (final = min(raw,25) when Market==0 or Property_Type==0), clamp to [0,100], emit exactly one fit/risk reason per component, and raise `ScoringInputError` (no numeric score, no mutation) when property/buy_box is null or missing `city`/`property_type`/`markets`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3_

- [x] 4. Scoring engine tests
  - [x] 4.1 Write Hypothesis strategies and per-criterion + full-property unit tests
    - In `api/tests/test_scoring.py` build Hypothesis strategies that generate valid and edge-laden `PropertyInput`/`BuyBoxInput` values (null bounds, arv 0/None, null `arv_pct_max`, out-of-vocab and null enums, mixed-case/whitespace-padded strings, prices straddling the 10% band, ARV% straddling the +5.00pp band)
    - Add one representative unit test per component (market hit/miss, each strategy branch, price in/near/out, ARV under/slightly-over/well-over, type hit/miss, beds/baths met/below/unverifiable)
    - Add the four named full-property fixtures: perfect match (score 100), market miss (score capped <= 25), price edge (10 price points + risk reason), ARV over ceiling (74% vs 70% -> 7 ARV points + "slightly above" reason)
    - _Requirements: 2.4, 2.9, 3.1, 4.2, 5.5_

  - [x] 4.2 Write property test for scoring determinism
    - **Property 1: Scoring determinism** — call `score()` twice on the same inputs and assert identical `score` and `reasons`
    - Tag `# Feature: buybox-matcher, Property 1: Scoring determinism`; run >= 100 iterations
    - **Validates: Requirements 2.1**

  - [x] 4.3 Write property test for component bounds and weight sum
    - **Property 2: Component scores never exceed configured weights and weights sum to 100**
    - Tag `# Feature: buybox-matcher, Property 2: ...`; run >= 100 iterations
    - **Validates: Requirements 2.2**

  - [x] 4.4 Write property test for score range
    - **Property 3: Score is an integer within [0, 100]**
    - Tag `# Feature: buybox-matcher, Property 3: ...`; run >= 100 iterations
    - **Validates: Requirements 2.3**

  - [x] 4.5 Write property test for reason count
    - **Property 4: Exactly one reason per component** — `len(fit) + len(risk) == 6` and all reason strings non-empty
    - Tag `# Feature: buybox-matcher, Property 4: ...`; run >= 100 iterations
    - **Validates: Requirements 2.4**

  - [x] 4.6 Write property test for hard-filter cap
    - **Property 5: Hard-filter cap** — when Market==0 or Property_Type==0, final score <= 25
    - Tag `# Feature: buybox-matcher, Property 5: ...`; run >= 100 iterations
    - **Validates: Requirements 2.9**

  - [x] 4.7 Write property test for market match scoring
    - **Property 6: Market match scoring (case-insensitive, trimmed)** — 30+fit iff trimmed/case-folded city matches a market, else 0+risk
    - Tag `# Feature: buybox-matcher, Property 6: ...`; run >= 100 iterations
    - **Validates: Requirements 2.5, 2.6**

  - [x] 4.8 Write property test for property-type match scoring
    - **Property 7: Property-type match scoring (case-insensitive, trimmed)** — 10+fit iff normalized types equal, else 0+risk
    - Tag `# Feature: buybox-matcher, Property 7: ...`; run >= 100 iterations
    - **Validates: Requirements 2.7, 2.8**

  - [x] 4.9 Write property test for strategy-mapping scoring
    - **Property 8: Strategy-mapping scoring** — 20+fit exactly for wholesale (any), distressed/light_rehab+flip/brrrr, turnkey+buy_and_hold; 0+risk otherwise including null/out-of-vocab strategy and condition
    - Tag `# Feature: buybox-matcher, Property 8: ...`; run >= 100 iterations
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

  - [x] 4.10 Write property test for price-range scoring
    - **Property 9: Price-range scoring with partial credit** — 20/10/0 bands for both-null, both-present, and single-bound cases with exactly one corresponding reason
    - Tag `# Feature: buybox-matcher, Property 9: ...`; run >= 100 iterations
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5**

  - [x] 4.11 Write property test for ARV% scoring and computation
    - **Property 10: ARV% scoring and computation** — null/zero arv -> 0+risk (no compute); null ceiling -> 0+risk; else `round_half_up(price/arv*100,2)` with 15/7/0 bands
    - Tag `# Feature: buybox-matcher, Property 10: ...`; run >= 100 iterations
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6**

  - [x] 4.12 Write property test for beds/baths minimum scoring
    - **Property 11: Beds/baths minimum scoring** — 5+fit when each min is null or met; 0+risk "could not verify" when min non-null and value null; 0+risk "below minimum" when value below min
    - Tag `# Feature: buybox-matcher, Property 11: ...`; run >= 100 iterations
    - **Validates: Requirements 6.1, 6.2, 6.3**

  - [x] 4.13 Write property test for invalid scoring input
    - **Property 12: Invalid scoring input is rejected without mutation** — null/missing `city`/`property_type`/`markets` signals an error, produces no numeric score, leaves inputs unmodified
    - Tag `# Feature: buybox-matcher, Property 12: ...`; run >= 100 iterations
    - **Validates: Requirements 2.10**

  - [x] 4.14 Checkpoint - scoring engine and property tests pass
    - Run the backend test suite (`pytest api/tests/test_scoring.py`) and ensure all scoring unit and property tests pass. Ensure all tests pass, ask the user if questions arise.

- [x] 5. Match endpoint and orchestration
  - [x] 5.1 Implement Match_Service ordering and filter-then-limit helpers
    - Add pure helpers (e.g. in `api/main.py` or a `matching.py` module) that sort matches by `score` desc then `buyer_id` asc, and apply `min_score` filter strictly before `limit`
    - _Requirements: 7.3, 7.6, 7.7_

  - [x] 5.2 Write property test for match ordering
    - **Property 13: Match ordering** — result ordered by score desc, buyer_id asc tie-break (total, stable)
    - Tag `# Feature: buybox-matcher, Property 13: ...`; run >= 100 iterations
    - **Validates: Requirements 7.3**

  - [x] 5.3 Write property test for filter-then-limit retrieval
    - **Property 14: Filter-then-limit retrieval** — every result has score >= min_score, count <= limit, equals sort -> filter -> truncate
    - Tag `# Feature: buybox-matcher, Property 14: ...`; run >= 100 iterations
    - **Validates: Requirements 7.6, 7.7**

  - [x] 5.4 Implement POST /match route and orchestration
    - Validate `min_score` (0..100 int) and `limit` (>=1 int) query params before any persistence; on failure return 422 and persist nothing
    - Persist the property, load all buyers+buy_boxes, score each via the pure engine, persist each match `{property_id, buyer_id, score, reasons}`, then sort/filter/limit and return 200 `{property_id, matches}` (empty array when no buyers)
    - Reject malformed bodies with 422 via the `PropertyInput` model without touching stored data
    - _Requirements: 7.1, 7.2, 7.4, 7.5, 7.8, 10.4, 10.8_

  - [x] 5.5 Write integration tests for the match endpoint
    - Cover happy path (200 with sorted matches), empty-buyer-set (200 empty array), `min_score`/`limit` behavior, invalid query param 422 with nothing persisted, and malformed-body 422
    - _Requirements: 7.1, 7.2, 7.4, 7.5, 7.8, 10.4, 10.8_

- [x] 6. AI extraction and buyer endpoints
  - [x] 6.1 Implement extract.py provider adapter and extraction pipeline
    - Build a thin provider adapter exposing `complete_json(system, user) -> str` selected by `AI_PROVIDER`, with a strict-JSON system prompt enumerating the nine Buy_Box fields, allowed enum vocabularies, and the null-for-absent rule
    - Implement `extract_buy_box(raw_text)`: call the provider with a 30s timeout, `json.loads` the result, coerce/validate via `BuyBoxModel`, and raise `ExtractionError` on timeout/provider error/unparseable output
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.9, 14.1_

  - [x] 6.2 Implement POST /buy-boxes/extract and GET /buyers routes
    - On extract: reject whitespace-only `raw_text` with 422 before invoking the provider and persisting; map unparseable output to 422; map `price_min > price_max` to 422; on success persist buyer + buy_box (1:1) and return 201 `{buyer_id, buy_box}`; persist nothing on any failure
    - On `GET /buyers`: return 200 array of `{buyer_id, name, company, buy_box}` (empty when none)
    - _Requirements: 1.7, 1.8, 1.10, 1.11, 10.1, 10.2, 10.3, 10.8_

  - [x] 6.3 Write property test for whitespace-only raw_text rejection
    - **Property 15: Whitespace-only raw_text is rejected** — whitespace/empty strings yield 422, provider not invoked, nothing persisted
    - Tag `# Feature: buybox-matcher, Property 15: ...`; run >= 100 iterations
    - **Validates: Requirements 1.8**

  - [x] 6.4 Write property test for price-range validation invariant
    - **Property 16: Price-range validation invariant** — non-null pair accepted iff `price_min <= price_max`, else 422 and nothing persisted
    - Tag `# Feature: buybox-matcher, Property 16: ...`; run >= 100 iterations
    - **Validates: Requirements 1.10**

  - [x] 6.5 Write integration tests for extraction with a mocked provider
    - Valid JSON -> 201; partial JSON -> null fields (no inference); non-JSON -> 422; provider error/timeout -> error with nothing persisted; `GET /buyers` happy path and empty array
    - _Requirements: 1.1, 1.3, 1.7, 1.9, 1.11, 10.2, 10.3_

  - [x] 6.6 Checkpoint - backend match and extract flows pass
    - Run the full backend test suite and ensure all unit, property, and integration tests pass. Ensure all tests pass, ask the user if questions arise.

- [x] 7. Synthetic seed data
  - [x] 7.1 Implement scripts/seed.py idempotent synthetic generator
    - Generate 140-160 buyers each with exactly one buy_box, tagged synthetic (sentinel marker) for idempotent skip-or-clear-then-reinsert within a transaction so reruns never duplicate or push count outside 140-160
    - Seed 8 explicit coverage fixtures (all four strategies and four property types) then randomize the remainder; draw `markets` from {Tampa, Lakeland, Orlando, Dallas, Houston, Cleveland, Nashville, Jacksonville}; keep `price_min`/`price_max` in [50k,600k] with `price_min<=price_max`, `arv_pct_max` in [65,80], `condition` in the four values, `min_beds` in [0,6], `min_baths` in [0,5], non-empty synthetic `raw_text`
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

  - [x] 7.2 Write seed verification tests
    - Assert run yields 140-160 buyers each with one buy_box; rerun is idempotent (count in range, no duplicates); all strategies/types represented; `markets` subset of allowed set; numeric fields within specified ranges
    - _Requirements: 11.1, 11.2, 11.4, 11.5_

- [x] 8. Message draft stub
  - [x] 8.1 Implement messaging.py and POST /match/{buyer_id}/message
    - Implement `draft_message(buyer, buy_box, property_in)` as a deterministic template referencing at least one buyer `markets` value and the property `address` or `city`, length 1..480, never transmitting
    - Add the route returning 200 `{channel:"sms", text}` for an existing buyer and 404 for an unknown buyer (drafter not invoked on 404)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 10.5, 10.6, 15.1_

  - [x] 8.2 Write property test for message draft content invariant
    - **Property 17: Message draft content invariant** — draft references a buyer market and the property address/city, length in [1,480]
    - Tag `# Feature: buybox-matcher, Property 17: ...`; run >= 100 iterations
    - **Validates: Requirements 8.1**

  - [x] 8.3 Write unit tests for the message route
    - Cover 200 success shape, 404 unknown buyer with no draft generated, and assert no outbound messaging client is invoked
    - _Requirements: 8.2, 8.3, 8.4, 10.5, 10.6, 15.1_

- [x] 9. Frontend scaffold and shared infrastructure
  - [x] 9.1 Scaffold Vite + TS + Tailwind project with types and API client
    - Initialize `web/` (Vite React-TS), configure Tailwind, add `web/src/types.ts` mirroring API response shapes, and `web/src/lib/api.ts` typed fetch client reading `VITE_API_URL` only (no provider/DB keys), with centralized timeout and error normalization
    - _Requirements: 14.2_

  - [x] 9.2 Implement App.tsx router and shared pure helpers
    - Add `web/src/main.tsx` root render and `web/src/App.tsx` router with `/extract` and `/match` routes
    - Add pure helper functions for the ARV% display (`price/arv*100` rounded to 1 decimal) and the score->tier mapping (green >=80, amber 50-79, gray <50) for reuse and testing
    - _Requirements: 13.2, 13.5, 13.6, 13.7_

  - [x] 9.3 Write frontend property test for ARV% display computation
    - **Property 18: ARV% display computation** — for price>0 and arv>0, computed Deal_ARV_Pct equals `price/arv*100` rounded to one decimal
    - Vitest + fast-check; tag `# Feature: buybox-matcher, Property 18: ARV% display computation`; run >= 100 iterations
    - **Validates: Requirements 13.2**

  - [x] 9.4 Write frontend property test for score color-tier mapping
    - **Property 19: Score color-tier mapping** — for integer score in [0,100], green if >=80, amber if 50-79, gray if <50 (partitioned, no overlap/gap)
    - Vitest + fast-check; tag `# Feature: buybox-matcher, Property 19: Score color-tier mapping`; run >= 100 iterations
    - **Validates: Requirements 13.5, 13.6, 13.7**

- [x] 10. Extract screen
  - [x] 10.1 Implement BuyBoxCard component
    - Render each Buy_Box field as a labeled chip; null fields render as a muted "not specified" chip
    - _Requirements: 12.3_

  - [x] 10.2 Implement ExtractPage with states
    - Provide textarea (<=10,000 chars) and optional name/company (<=100 chars) inputs; block whitespace-only submit with "a message is required"; show a loading indicator and disable Extract while in progress; on 201 render `BuyBoxCard` chips and a save confirmation within 2s; on 422 show "could not be parsed" and retain entered values
    - Wire to `api.ts` and the `/extract` route
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7_

  - [x] 10.3 Write component tests for ExtractPage
    - Cover chips render, loading disables Extract, whitespace guard, 422 retention, and save confirmation
    - _Requirements: 12.3, 12.4, 12.5, 12.6, 12.7_

- [x] 11. Match screen
  - [x] 11.1 Implement PropertyForm with live ARV% display
    - Address/city text, price/arv/beds/baths numeric, property_type/condition selects; display live Deal_ARV_Pct (1 decimal) while price>0 and arv>0; suppress it and show "arv must be greater than 0" when arv is empty/0 (reuse the Task 9.2 helper)
    - _Requirements: 13.1, 13.2, 13.3_

  - [x] 11.2 Implement MatchRow component
    - Score badge tier via the Task 9.2 helper (>=80 green, 50-79 amber, <50 gray); fit chips green and risk chips amber; draft control opens a modal labeled "not sent" showing the returned draft text
    - _Requirements: 13.4, 13.5, 13.6, 13.7, 13.8, 13.9_

  - [x] 11.3 Implement MatchPage with states and wiring
    - Submit the property form to `/match`, render `MatchRow`s ordered by descending score; disable "Find Buyers" and show a loading indicator during match/draft requests; on failure or >10s timeout show "matches could not be retrieved", retain form values, re-enable the control; on zero matches show "no buyers matched"; wire the draft control to `POST /match/{buyer_id}/message`
    - _Requirements: 13.4, 13.9, 13.10, 13.11, 13.12_

  - [x] 11.4 Write component tests for MatchPage and MatchRow
    - Cover rows ordered desc, chip styles, color tiers, draft modal "not sent" label, and empty/loading/error/timeout states
    - _Requirements: 13.4, 13.5, 13.6, 13.7, 13.8, 13.9, 13.10, 13.11, 13.12_

  - [x] 11.5 Checkpoint - frontend builds and tests pass
    - Run the frontend build and test suite (`npm run build`, Vitest) and ensure all property and component tests pass. Ensure all tests pass, ask the user if questions arise.

- [x] 12. Polish and deployment config
  - [x] 12.1 Finalize error/empty/loading states and env examples
    - Audit Extract and Match screens for consistent loading, empty, and error states
    - Add `api/.env.example` (documenting `AI_PROVIDER`, provider key, `SUPABASE_URL`, `SUPABASE_KEY`, `ALLOWED_ORIGIN`, no real secrets) and `web/.env.example` (documenting only `VITE_API_URL`)
    - _Requirements: 12.4, 12.7, 13.10, 13.11, 13.12, 14.2, 14.3_

  - [x] 12.2 Write run instructions in README
    - Document backend setup (migration, env, run), seed script invocation, and frontend setup/run steps
    - _Requirements: 11.1, 14.2, 14.3_

  - [x] 12.3 Final checkpoint - full suite passes
    - Run backend and frontend test suites end to end and ensure everything passes. Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each task references specific requirement clauses for traceability.
- Property-based test tasks reference the design's Correctness Properties (Properties 1-19) by number; each runs at >= 100 iterations and is tagged `# Feature: buybox-matcher, Property N: ...`. Properties 1-17 are backend (Hypothesis); Properties 18-19 are frontend (Vitest + fast-check).
- The scoring property tests (Task 4) sit immediately after the scoring engine (Task 3) so correctness is validated test-driven before orchestration is built on top.
- Checkpoints provide incremental validation at natural breaks.

## Task Dependency Graph

Same-file tasks are placed in separate waves to avoid write conflicts. The backend `main.py` route tasks (2.5, 5.4, 6.2, 8.1) and the single-file scoring property tests (4.2-4.13, all in `test_scoring.py`) are therefore spread across waves; the long tail of single-task waves is the scoring property tests serialized against that one file. Frontend work runs in parallel with backend work where files do not overlap.

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "9.1"] },
    { "id": 1, "tasks": ["2.2", "2.3", "9.2"] },
    { "id": 2, "tasks": ["2.4", "2.5", "9.3", "9.4", "10.1", "11.1", "11.2"] },
    { "id": 3, "tasks": ["3.1", "2.6", "10.2", "11.3"] },
    { "id": 4, "tasks": ["4.1", "5.1", "6.1", "10.3", "11.4"] },
    { "id": 5, "tasks": ["4.2", "5.4", "7.1", "12.1"] },
    { "id": 6, "tasks": ["4.3", "6.2", "5.2", "7.2", "12.2"] },
    { "id": 7, "tasks": ["4.4", "8.1", "5.3", "6.5"] },
    { "id": 8, "tasks": ["4.5", "5.5", "6.3", "8.2"] },
    { "id": 9, "tasks": ["4.6", "6.4", "8.3"] },
    { "id": 10, "tasks": ["4.7"] },
    { "id": 11, "tasks": ["4.8"] },
    { "id": 12, "tasks": ["4.9"] },
    { "id": 13, "tasks": ["4.10"] },
    { "id": 14, "tasks": ["4.11"] },
    { "id": 15, "tasks": ["4.12"] },
    { "id": 16, "tasks": ["4.13"] }
  ]
}
```
