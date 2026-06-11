# Requirements Document

## Introduction

BuyBox Matcher is a two-screen web application for the real-estate wholesaling/disposition ("dispo") domain. It turns messy, free-text real-estate-investor messages into structured purchase criteria ("buy boxes"), then scores a property deal against every saved buyer and returns a ranked, explainable list of matches.

The product has two core flows:

1. **Extract** — A user pastes a raw investor message. A server-side AI extraction step parses the message into a structured buy box conforming to a strict schema, and the buyer is saved.
2. **Match** — A user enters a property deal. A deterministic, weighted, rule-based scoring engine ranks all saved buyers by fit, producing a 0-100 score and plain-English fit/risk reasons for each.

The system is intentionally scoped as a demo-first artifact: AI is used only at the edges (extraction and message drafting), while the match decision is a pure, deterministic function. Synthetic seed data ensures the Match flow works on first run. The product explicitly excludes real message sending, authentication, real investor data, and pipeline management.

The stack is React 18 + TypeScript + Vite + Tailwind (frontend), FastAPI / Python 3.11+ (backend), Supabase / Postgres (database), and OpenAI or Anthropic (AI, server-side only), deployed on Vercel + Render/Railway + Supabase.

## Glossary

- **System**: The BuyBox Matcher application as a whole, including frontend, backend, and database.
- **Extraction_Service**: The server-side backend component that converts a raw investor message into a structured buy box using an AI provider.
- **AI_Provider**: The external OpenAI or Anthropic language-model service used by the Extraction_Service and Message_Drafter, accessed only from the backend.
- **Scoring_Engine**: The pure, deterministic backend function `score(property, buy_box) -> {score, reasons}` that computes a 0-100 match score and fit/risk reasons.
- **Scoring_Config**: A single configuration object holding all scoring weights and thresholds used by the Scoring_Engine.
- **Match_Service**: The backend component that persists a property, invokes the Scoring_Engine against all saved buyers, persists matches, and returns a ranked list.
- **Message_Drafter**: The backend stub component that generates a first-touch SMS draft text for a matched buyer without sending it.
- **Seed_Script**: The backend script that inserts synthetic buyers and buy boxes into the database.
- **API**: The FastAPI backend HTTP interface exposing the application's endpoints.
- **Web_App**: The React frontend with the Extract and Match screens.
- **Extract_Screen**: The frontend route (`/extract`) for pasting a message and saving a buyer.
- **Match_Screen**: The frontend route (`/match`) for entering a property and viewing ranked matches.
- **Buy_Box**: A buyer's structured purchase criteria (markets, strategy, property_type, price_min, price_max, arv_pct_max, min_beds, min_baths, condition).
- **Buyer**: A cash buyer / investor record (name, company, optional email/phone) with one associated Buy_Box.
- **Property**: A property deal record (address, city, price, arv, beds, baths, optional sqft, property_type, condition).
- **Match**: A computed score linking a Property to a Buyer, including the 0-100 score and reasons.
- **Deal_ARV_Pct**: The derived value `property.price / property.arv * 100`, computed at match time and not stored on the Property.
- **Reasons**: An object `{ fit: [string], risk: [string] }` of plain-English explanations attached to a Match.
- **Strategy**: An enumerated buyer investment strategy: `fix_and_flip`, `buy_and_hold`, `brrrr`, or `wholesale`.
- **Property_Type**: An enumerated property category: `single_family`, `multi_family`, `condo`, or `land`.
- **Condition**: An enumerated property/buyer condition value: `distressed`, `light_rehab`, `turnkey`, or `any`.

## Requirements

### Requirement 1: AI Buy Box Extraction

**User Story:** As a wholesaler, I want to paste a raw investor message and get back structured purchase criteria, so that I can save a buyer without manually entering each field.

#### Acceptance Criteria

1. WHEN a request to extract a buy box is received with a `raw_text` field that contains at least one non-whitespace character and is no longer than 10,000 characters, THE Extraction_Service SHALL invoke the AI_Provider to produce a structured Buy_Box conforming to the Buy_Box schema.
2. THE Extraction_Service SHALL return a Buy_Box containing the fields `markets`, `strategy`, `property_type`, `price_min`, `price_max`, `arv_pct_max`, `min_beds`, `min_baths`, and `condition`.
3. WHERE a Buy_Box field is not present in the `raw_text`, THE Extraction_Service SHALL set that field to `null` and SHALL NOT infer absent values.
4. THE Extraction_Service SHALL set `strategy` to one of `fix_and_flip`, `buy_and_hold`, `brrrr`, or `wholesale`, or to `null` when no strategy is present.
5. THE Extraction_Service SHALL set `property_type` to one of `single_family`, `multi_family`, `condo`, or `land`, or to `null` when no property type is present.
6. THE Extraction_Service SHALL set `condition` to one of `distressed`, `light_rehab`, `turnkey`, or `any`, or to `null` when no condition is present.
7. IF the `raw_text` cannot be parsed into a usable Buy_Box, THEN THE API SHALL respond with HTTP status 422 and an error description, and SHALL NOT persist a Buyer or Buy_Box.
8. IF the `raw_text` field is missing, empty, or contains only whitespace, THEN THE API SHALL respond with HTTP status 422 and an error description indicating that `raw_text` is required, and SHALL NOT invoke the AI_Provider and SHALL NOT persist any data.
9. IF the AI_Provider returns an error or does not respond within 30 seconds, THEN THE API SHALL respond with an error status and a description indicating extraction failed, and SHALL NOT persist a Buyer or Buy_Box.
10. IF both `price_min` and `price_max` are non-null and `price_min` is greater than `price_max`, THEN THE API SHALL respond with HTTP status 422 and an error description indicating the price range is invalid, and SHALL NOT persist a Buyer or Buy_Box.
11. WHEN a Buy_Box is successfully extracted and its `price_min` and `price_max` satisfy the constraint that `price_min` is less than or equal to `price_max` whenever both are non-null, THE API SHALL persist a Buyer and the associated Buy_Box and respond with HTTP status 201 containing `buyer_id` and `buy_box`.

### Requirement 2: Deterministic Scoring Engine

**User Story:** As a wholesaler, I want each buyer scored by an explainable rule-based engine, so that I can trust why a buyer ranks where they do.

#### Acceptance Criteria

1. THE Scoring_Engine SHALL be a pure function that, given identical Property and Buy_Box inputs, returns identical `score` and `reasons` outputs with no dependence on external or mutable state.
2. THE Scoring_Engine SHALL read all weights and thresholds from a single Scoring_Config object, where the weights sum to exactly 100 (Market 30, Strategy 20, Price 20, ARV% 15, Property_Type 10, Beds/Baths 5).
3. THE Scoring_Engine SHALL return a `score` that is an integer between 0 and 100 inclusive.
4. THE Scoring_Engine SHALL return `reasons` as an object containing a `fit` array of non-empty strings and a `risk` array of non-empty strings, where every awarded or withheld weight component contributes exactly one corresponding entry to either the `fit` or `risk` array.
5. WHEN the Property `city` matches an entry in the Buy_Box `markets` using a case-insensitive, leading/trailing-whitespace-trimmed comparison, THE Scoring_Engine SHALL award the full Market weight of 30 points and add a market fit reason.
6. IF the Property `city` does not match any entry in the Buy_Box `markets` using a case-insensitive, leading/trailing-whitespace-trimmed comparison, THEN THE Scoring_Engine SHALL award 0 Market points and add a market risk reason.
7. WHEN the Property `property_type` matches the Buy_Box `property_type` using a case-insensitive, leading/trailing-whitespace-trimmed comparison, THE Scoring_Engine SHALL award the full Property_Type weight of 10 points and add a property-type fit reason.
8. IF the Property `property_type` does not match the Buy_Box `property_type` using a case-insensitive, leading/trailing-whitespace-trimmed comparison, THEN THE Scoring_Engine SHALL award 0 Property_Type points and add a property-type risk reason.
9. IF the Property `city` does not match any Buy_Box `markets` entry, OR the Property `property_type` does not match the Buy_Box `property_type`, THEN THE Scoring_Engine SHALL cap the total `score` at a maximum of 25 points regardless of points awarded by other components.
10. IF the Property input or the Buy_Box input is null, or is missing any field required for scoring (`city`, `property_type`, or `markets`), THEN THE Scoring_Engine SHALL return without producing a numeric `score` and SHALL provide an error indication identifying the missing or invalid input, while leaving the input data unmodified.

### Requirement 3: Strategy Fit Scoring

**User Story:** As a wholesaler, I want the engine to match a deal's profile to a buyer's strategy, so that distressed deals reach flippers and turnkey deals reach hold buyers.

#### Acceptance Criteria

1. WHEN the Property `condition` is `distressed` or `light_rehab` AND the Buy_Box `strategy` is `fix_and_flip` or `brrrr`, THE Scoring_Engine SHALL set the Strategy criterion score to exactly 20 points and add a strategy fit reason to the fit reason list.
2. WHEN the Property `condition` is `turnkey` AND the Buy_Box `strategy` is `buy_and_hold`, THE Scoring_Engine SHALL set the Strategy criterion score to exactly 20 points and add a strategy fit reason to the fit reason list.
3. WHERE the Buy_Box `strategy` is `wholesale`, THE Scoring_Engine SHALL set the Strategy criterion score to exactly 20 points and add a strategy fit reason to the fit reason list for any Property regardless of its `condition` value.
4. IF the Property `condition` and the Buy_Box `strategy` are both non-null AND the Property `condition` is not listed as a suitable profile for the Buy_Box `strategy` under the strategy mapping, THEN THE Scoring_Engine SHALL set the Strategy criterion score to exactly 0 points and add a strategy risk reason to the risk reason list.
5. IF the Property `condition` is null or is a value outside the defined set (`distressed`, `light_rehab`, `turnkey`) AND the Buy_Box `strategy` is not `wholesale`, THEN THE Scoring_Engine SHALL set the Strategy criterion score to exactly 0 points and add a strategy risk reason indicating the deal profile could not be determined to the risk reason list.
6. IF the Buy_Box `strategy` is null or is a value outside the defined set (`fix_and_flip`, `brrrr`, `buy_and_hold`, `wholesale`), THEN THE Scoring_Engine SHALL set the Strategy criterion score to exactly 0 points and add a strategy risk reason indicating the buyer strategy could not be determined to the risk reason list.

### Requirement 4: Price Range Scoring

**User Story:** As a wholesaler, I want price fit scored with partial credit near the edges, so that deals just outside a buyer's range are not dismissed outright.

#### Acceptance Criteria

1. WHEN the Buy_Box `price_min` and `price_max` are both non-null AND the Property `price` is greater than or equal to `price_min` AND less than or equal to `price_max`, THE Scoring_Engine SHALL award the full Price weight of 20 points and add a price fit reason.
2. IF the Buy_Box `price_min` and `price_max` are both non-null AND the Property `price` is below `price_min` but greater than or equal to 90 percent of `price_min`, OR the Property `price` is above `price_max` but less than or equal to 110 percent of `price_max`, THEN THE Scoring_Engine SHALL award 10 Price points and add a price risk reason indicating the price is near the buyer's limit.
3. IF the Buy_Box `price_min` and `price_max` are both non-null AND the Property `price` is below 90 percent of `price_min`, OR the Property `price` is above 110 percent of `price_max`, THEN THE Scoring_Engine SHALL award 0 Price points and add a price risk reason indicating the price is outside range.
4. WHILE exactly one of the Buy_Box `price_min` or `price_max` is null, THE Scoring_Engine SHALL evaluate price fit against only the non-null bound, awarding 20 points when the Property `price` satisfies that bound, 10 points when the Property `price` violates that bound by no more than 10 percent of the bound value, and 0 points when the Property `price` violates that bound by more than 10 percent of the bound value, adding the corresponding price fit or price risk reason.
5. WHEN both the Buy_Box `price_min` and `price_max` are null, THE Scoring_Engine SHALL award the full Price weight of 20 points and add a price fit reason indicating no price bound was specified.

### Requirement 5: ARV Percentage Scoring

**User Story:** As a wholesaler, I want the deal's ARV percentage scored against the buyer's ceiling with partial credit, so that deals slightly above the ceiling are still surfaced as risks.

#### Acceptance Criteria

1. WHEN `property.arv` is greater than 0 and is not null, THE Scoring_Engine SHALL compute Deal_ARV_Pct as `property.price / property.arv * 100` at match time, rounded to 2 decimal places (round half up).
2. IF `property.arv` is 0 or null, THEN THE Scoring_Engine SHALL skip the Deal_ARV_Pct computation, award 0 ARV points, and add an ARV risk reason indicating the ARV percentage could not be evaluated due to a missing or zero ARV value.
3. IF the Buy_Box `arv_pct_max` is null, THEN THE Scoring_Engine SHALL award 0 ARV points and add an ARV risk reason indicating no ARV ceiling is defined for the buyer.
4. WHEN Deal_ARV_Pct is computed and is less than or equal to the Buy_Box `arv_pct_max`, THE Scoring_Engine SHALL award the full ARV weight of 15 points and add an ARV fit reason.
5. IF Deal_ARV_Pct is computed and is greater than the Buy_Box `arv_pct_max` by 5.00 percentage points or fewer, THEN THE Scoring_Engine SHALL award 7 ARV points and add an ARV risk reason indicating the deal is slightly above the buyer's ceiling.
6. IF Deal_ARV_Pct is computed and exceeds the Buy_Box `arv_pct_max` by more than 5.00 percentage points, THEN THE Scoring_Engine SHALL award 0 ARV points and add an ARV risk reason indicating the deal is well above the buyer's ceiling.

### Requirement 6: Beds and Baths Minimum Scoring

**User Story:** As a wholesaler, I want minimum bed and bath requirements scored, so that deals below a buyer's minimums are flagged.

#### Acceptance Criteria

1. WHEN the Buy_Box `min_beds` is null OR the Property `beds` is greater than or equal to the Buy_Box `min_beds`, AND the Buy_Box `min_baths` is null OR the Property `baths` is greater than or equal to the Buy_Box `min_baths`, THE Scoring_Engine SHALL award the full Beds/Baths weight of 5 points and add a beds/baths fit reason.
2. IF the Buy_Box `min_beds` is non-null AND the Property `beds` is non-null AND less than the Buy_Box `min_beds`, OR the Buy_Box `min_baths` is non-null AND the Property `baths` is non-null AND less than the Buy_Box `min_baths`, THEN THE Scoring_Engine SHALL award 0 Beds/Baths points and add a beds/baths risk reason.
3. IF the Buy_Box `min_beds` is non-null and the Property `beds` is null, OR the Buy_Box `min_baths` is non-null and the Property `baths` is null, THEN THE Scoring_Engine SHALL award 0 Beds/Baths points and add a beds/baths risk reason indicating the minimum could not be verified.

### Requirement 7: Match Ranking and Retrieval

**User Story:** As a wholesaler, I want to submit a property deal and get a ranked list of all matching buyers, so that I can prioritize who to contact first.

#### Acceptance Criteria

1. WHEN a match request is received with Property fields, THE Match_Service SHALL persist the Property and score it against every saved Buyer using the Scoring_Engine, producing an integer `score` between 0 and 100 inclusive for each Buyer.
2. THE Match_Service SHALL persist each computed Match including `score` and `reasons`.
3. THE Match_Service SHALL return the matches sorted by `score` in descending order, and for matches with equal `score` SHALL order them by `buyer_id` in ascending order.
4. WHEN a match request completes successfully, THE API SHALL respond with HTTP status 200 containing `property_id` and a `matches` array.
5. IF no Buyer is saved at the time of a match request, THEN THE API SHALL respond with HTTP status 200 containing `property_id` and an empty `matches` array.
6. WHERE a `min_score` query parameter is provided, THE Match_Service SHALL return only matches with a `score` greater than or equal to the `min_score` value, applying this filter before any `limit` is applied.
7. WHERE a `limit` query parameter is provided, THE Match_Service SHALL return at most `limit` matches, selected after sorting and after applying any `min_score` filter.
8. IF the `min_score` query parameter is not an integer between 0 and 100 inclusive, or the `limit` query parameter is not an integer greater than or equal to 1, THEN THE API SHALL respond with HTTP status 422, SHALL NOT persist the Property, and SHALL NOT persist any Match, returning an error response indicating the invalid query parameter.

### Requirement 8: Message Draft Stub

**User Story:** As a wholesaler, I want a first-touch message draft generated for a matched buyer, so that I can quickly start an outreach without composing it from scratch.

#### Acceptance Criteria

1. WHEN a message draft is requested for an existing Buyer, THE Message_Drafter SHALL generate SMS draft text that references at least one of the Buyer's `markets` values and the relevant Property's `address` or `city`, with a length between 1 and 480 characters inclusive.
2. WHEN a message draft is successfully generated, THE API SHALL respond with HTTP status 200 containing a `channel` field set to `sms` and a non-empty `text` field holding the draft text.
3. THE Message_Drafter SHALL produce the draft text only and SHALL NOT transmit the message through any external channel.
4. IF a message draft is requested for a `buyer_id` that does not correspond to an existing Buyer, THEN THE API SHALL respond with HTTP status 404 and an error description indicating the Buyer was not found, and THE Message_Drafter SHALL NOT generate draft text.

### Requirement 9: Data Persistence

**User Story:** As a developer, I want buyers, buy boxes, properties, and matches stored in Postgres, so that results are inspectable and repeatable.

#### Acceptance Criteria

1. THE System SHALL store Buyer records with a generated `id` (uuid) as primary key, a required `name` (text), nullable `company`, `email`, and `phone` (text), and a `created_at` (timestamptz) defaulting to the current timestamp at insertion.
2. THE System SHALL store Buy_Box records with a generated `id` (uuid) as primary key, a `buyer_id` (uuid) referencing a Buyer, `markets` (text array of city/metro names), `strategy`, `property_type`, and `condition` (text enums), `arv_pct_max` (integer, 0 to 100 inclusive), nullable `price_min`, `price_max`, `min_beds` (integers) and `min_baths` (numeric), `raw_text` (text), and a `created_at` (timestamptz) defaulting to the current timestamp at insertion, associated one-to-one with a Buyer.
3. THE System SHALL store Property records with a generated `id` (uuid) as primary key, required `address` and `city` (text), `price` and `arv` (integers), `beds` (integer) and `baths` (numeric), nullable `sqft` (integer), `property_type` and `condition` (text enums), and a `created_at` (timestamptz) defaulting to the current timestamp at insertion.
4. THE System SHALL store Match records with a generated `id` (uuid) as primary key, a `property_id` (uuid) referencing a Property, a `buyer_id` (uuid) referencing a Buyer, a `score` (integer, 0 to 100 inclusive), `reasons` stored as JSON containing a `fit` list and a `risk` list, and a `created_at` (timestamptz) defaulting to the current timestamp at insertion.
5. IF a `strategy`, `property_type`, or `condition` value submitted for persistence is not a member of its defined enumeration, THEN THE System SHALL reject the record, return an error indicating the invalid value, and not persist the record.
6. THE System SHALL NOT persist Deal_ARV_Pct on the Property record.
7. IF a Buy_Box is submitted for a `buyer_id` that already has an associated Buy_Box, THEN THE System SHALL reject the record, return an error indicating the one-to-one association is violated, and not persist the record.
8. IF a Match is submitted with a `property_id` or `buyer_id` that does not reference an existing Property or Buyer, THEN THE System SHALL reject the record, return an error indicating the unresolved reference, and not persist the record.

### Requirement 10: API Endpoints

**User Story:** As a frontend developer, I want a documented set of HTTP endpoints, so that the Web_App can drive the extract and match flows.

#### Acceptance Criteria

1. WHEN the API receives a `POST /buy-boxes/extract` request with a JSON body containing a non-empty `raw_text` string (maximum 10,000 characters) and optional `name` and `company` strings (each maximum 200 characters), THE API SHALL return HTTP status 201 with a JSON body containing `buyer_id` and `buy_box`.
2. IF a `POST /buy-boxes/extract` request body has a valid structure but the `raw_text` cannot be parsed into a usable buy box, THEN THE API SHALL return HTTP status 422 with a JSON body containing an error message indicating the text could not be parsed, and SHALL NOT persist a buyer record.
3. WHEN the API receives a `GET /buyers` request, THE API SHALL return HTTP status 200 with a JSON array in which each element contains `buyer_id`, `name`, `company`, and `buy_box` (the array SHALL be empty when no buyers are saved).
4. WHEN the API receives a `POST /match` request with a JSON body containing the Property fields (`address`, `city`, `price`, `arv`, `beds`, `baths`, `property_type`, `condition`), THE API SHALL return HTTP status 200 with a JSON body containing `property_id` and a `matches` array sorted by `score` in descending order.
5. WHEN the API receives a `POST /match/{buyer_id}/message` request for an existing `buyer_id`, THE API SHALL return HTTP status 200 with a JSON body containing `channel` and `text`.
6. IF a `POST /match/{buyer_id}/message` request references a `buyer_id` that does not match any saved buyer, THEN THE API SHALL return HTTP status 404 with a JSON body containing an error message indicating the buyer was not found.
7. WHEN the API receives a `GET /health` request, THE API SHALL return HTTP status 200 with the JSON body `{ "status": "ok" }`.
8. IF a request body to any endpoint that accepts JSON is malformed (invalid JSON syntax, missing required fields, or a field with an incorrect type), THEN THE API SHALL return HTTP status 422 with a JSON body identifying the invalid fields, and SHALL NOT modify any stored data.
9. WHEN the API receives a cross-origin request whose `Origin` header matches the configured `ALLOWED_ORIGIN` value, THE API SHALL include the matching `Access-Control-Allow-Origin` header in the response.
10. IF the API receives a cross-origin request whose `Origin` header does not match the configured `ALLOWED_ORIGIN` value, THEN THE API SHALL omit the `Access-Control-Allow-Origin` header from the response.

### Requirement 11: Synthetic Seed Data

**User Story:** As a developer, I want the database seeded with synthetic buyers, so that the Match flow works immediately on first clone without manual data entry.

#### Acceptance Criteria

1. WHEN the Seed_Script is run against a database that contains no synthetic seed dataset, THE Seed_Script SHALL insert between 140 and 160 synthetic Buyers, each with exactly one associated Buy_Box.
2. WHEN the Seed_Script is run and the synthetic seed dataset is already present, THE Seed_Script SHALL either skip insertion or clear and reinsert the synthetic dataset, and in both cases SHALL NOT create duplicate Buyer records and SHALL NOT increase the total Buyer count beyond the 140 to 160 range.
3. THE Seed_Script SHALL generate only synthetic data and SHALL NOT use real investor data.
4. THE Seed_Script SHALL produce a seed dataset that includes at least one Buy_Box for each of the four Strategy values (`fix_and_flip`, `buy_and_hold`, `brrrr`, `wholesale`) and at least one Buy_Box for each of the four Property_Type values (`single_family`, `multi_family`, `condo`, `land`), with each Buy_Box `markets` drawn from the set {Tampa, Lakeland, Orlando, Dallas, Houston, Cleveland, Nashville, Jacksonville}.
5. THE Seed_Script SHALL set each seeded Buy_Box such that `price_min` and `price_max` are within 50,000 to 600,000 inclusive with `price_min` less than or equal to `price_max`, `arv_pct_max` is between 65 and 80 inclusive, `condition` is one of `distressed`, `light_rehab`, `turnkey`, or `any`, `min_beds` is between 0 and 6 inclusive, `min_baths` is between 0 and 5 inclusive, and `raw_text` is a non-empty synthetic message.

### Requirement 12: Extract Screen

**User Story:** As a wholesaler, I want a screen to paste a message and review the extracted buy box, so that I can confirm and save a buyer.

#### Acceptance Criteria

1. THE Extract_Screen SHALL provide a text area for the message supporting up to 10,000 characters and optional input fields for the Buyer name (up to 100 characters) and company (up to 100 characters).
2. WHEN a user activates the Extract action with a message containing at least one non-whitespace character, THE Extract_Screen SHALL submit the message to the extraction API.
3. WHEN the extraction API returns a successful response, THE Extract_Screen SHALL display the returned Buy_Box as labeled chips.
4. WHILE an extraction request is in progress, THE Extract_Screen SHALL display a loading indicator and disable the Extract action.
5. IF a user activates the Extract action while the message is empty or contains only whitespace characters, THEN THE Extract_Screen SHALL prevent submission and display an error message indicating that a message is required.
6. WHEN a Buyer is saved successfully, THE Extract_Screen SHALL display a save confirmation within 2 seconds of receiving the save response.
7. IF the API responds with HTTP status 422, THEN THE Extract_Screen SHALL display an error message indicating the message could not be parsed and SHALL retain the entered message and input field values.

### Requirement 13: Match Screen

**User Story:** As a wholesaler, I want a screen to enter a property and view ranked matches with color-coded scores, so that I can quickly read fit and risk.

#### Acceptance Criteria

1. THE Match_Screen SHALL provide a property form with text fields for address, city, numeric fields for price, arv, beds, and baths, and selection controls for property_type and condition.
2. WHILE the property form contains a numeric `price` greater than 0 and a numeric `arv` greater than 0, THE Match_Screen SHALL display the auto-computed Deal_ARV_Pct, calculated as (price divided by arv) expressed as a percentage rounded to one decimal place.
3. IF a user submits the property form while `arv` is empty or equal to 0, THEN THE Match_Screen SHALL suppress the Deal_ARV_Pct value and display a validation message indicating that arv must be greater than 0.
4. WHEN a user submits the property form with all required fields populated, THE Match_Screen SHALL send a POST request to the /match endpoint and, upon a successful response, display each returned Match as a row ordered by descending score, where each row shows the numeric score, the fit reasons as fit chips, and the risk reasons as risk chips.
5. WHERE a Match `score` is greater than or equal to 80, THE Match_Screen SHALL display the score badge in the green tier.
6. WHERE a Match `score` is between 50 and 79 inclusive, THE Match_Screen SHALL display the score badge in the amber tier.
7. WHERE a Match `score` is less than 50, THE Match_Screen SHALL display the score badge in the gray tier.
8. THE Match_Screen SHALL display each fit chip in the green style and each risk chip in the amber style.
9. WHEN a user activates the draft message control for a Match, THE Match_Screen SHALL send a draft request to the API and, upon a successful response, display the returned draft text in a modal labeled "not sent" to indicate the message has not been sent.
10. WHILE a match request or a draft request is in progress, THE Match_Screen SHALL display a loading indicator and disable the Find Buyers control until the request completes or fails.
11. IF a successful match response contains zero Match rows, THEN THE Match_Screen SHALL display an empty-results message indicating that no buyers matched the submitted property.
12. IF a match request or a draft request fails or does not complete within 10 seconds, THEN THE Match_Screen SHALL display an error message indicating that matches could not be retrieved, retain the submitted form values, and re-enable the Find Buyers control.

### Requirement 14: Server-Side AI and Secret Handling

**User Story:** As a developer, I want all AI calls made server-side with no keys in the frontend, so that API credentials are never exposed to clients.

#### Acceptance Criteria

1. WHEN an AI operation is requested, THE System SHALL invoke the AI_Provider exclusively from the backend, with no direct AI_Provider calls originating from the Web_App.
2. THE Web_App SHALL NOT contain, store, or transmit any AI_Provider API keys (OPENAI_API_KEY or ANTHROPIC_API_KEY) or database credentials (SUPABASE_KEY), and its only configured external reference SHALL be VITE_API_URL.
3. WHEN the backend starts, THE System SHALL read AI_Provider selection (AI_PROVIDER), the corresponding AI_Provider API key (OPENAI_API_KEY or ANTHROPIC_API_KEY), and database credentials (SUPABASE_URL, SUPABASE_KEY) from backend environment configuration.
4. IF any required backend environment credential (AI_PROVIDER, the selected provider's API key, SUPABASE_URL, or SUPABASE_KEY) is missing or empty at startup, THEN THE System SHALL halt startup of AI-dependent operations and emit an error indicating which credential is missing, without exposing the credential value.
5. WHEN the Web_App requires an AI operation, THE Web_App SHALL request it through the backend API identified by VITE_API_URL, and THE System SHALL return only the operation result without including any AI_Provider API key or database credential in the response.

### Requirement 15: Scope Constraints (Non-Goals)

**User Story:** As a stakeholder, I want explicitly excluded features enforced as constraints, so that the build stays scoped to the core matching loop.

#### Acceptance Criteria

1. THE System SHALL NOT transmit any SMS or email message to a real external messaging or email gateway; any messaging behavior SHALL be limited to local simulation or display within the application interface, with zero outbound delivery requests to third-party SMS or email providers.
2. THE System SHALL NOT implement authentication mechanisms (login, credentials, sessions, or tokens) or multi-user account separation, and SHALL operate as a single shared context where no data is partitioned by user identity.
3. THE System SHALL NOT perform automated scraping, crawling, or fetching of investor data from any external website or third-party source, and SHALL operate exclusively on data that is manually entered or loaded from local seed or sample datasets.
4. THE System SHALL NOT implement a pipeline kanban feature, including any board, column, or stage-based drag-and-drop tracking of records.
5. THE System SHALL NOT implement skip tracing features, including any lookup or resolution of contact details (phone numbers, addresses, or owner identities) from external data sources.
6. THE System SHALL NOT implement payment, billing, or financial transaction processing features, including any collection, storage, or transmission of payment instrument data.
7. THE System SHALL NOT implement data enrichment features, including any augmentation of records with attributes retrieved from external data providers or APIs.
