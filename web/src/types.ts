/**
 * Shared TypeScript types mirroring the backend API response shapes.
 *
 * These types are the frontend-side mirror of the Pydantic models defined in
 * the design document ("Data Models" / `api/models.py`). Keeping them in one
 * place lets the API client (`lib/api.ts`) and every screen share a single
 * source of truth for the wire format.
 */

// --- Enumerations (mirror api/models.py Literals) -------------------------

export type Strategy = "fix_and_flip" | "buy_and_hold" | "brrrr" | "wholesale";

export type PropertyType = "single_family" | "multi_family" | "condo" | "land";

export type Condition = "distressed" | "light_rehab" | "turnkey" | "any";

// --- Buy Box --------------------------------------------------------------

/**
 * A buyer's structured purchase criteria. Mirrors `BuyBoxModel`.
 * Any field not present in the source message is `null` (null-for-absent),
 * except `markets` which is always an array.
 */
export interface BuyBox {
  markets: string[];
  strategy: Strategy | null;
  property_type: PropertyType | null;
  price_min: number | null;
  price_max: number | null;
  arv_pct_max: number | null;
  min_beds: number | null;
  min_baths: number | null;
  condition: Condition | null;
}

// --- Extract flow ---------------------------------------------------------

/** Request body for `POST /buy-boxes/extract`. */
export interface ExtractRequest {
  raw_text: string;
  name?: string | null;
  company?: string | null;
}

/** Success response (201) from `POST /buy-boxes/extract`. Mirrors `ExtractResponse`. */
export interface ExtractResponse {
  buyer_id: string;
  buy_box: BuyBox;
}

// --- Buyers list ----------------------------------------------------------

/** One element of the `GET /buyers` response array (Requirement 10.3). */
export interface BuyerListItem {
  buyer_id: string;
  name: string;
  company: string | null;
  buy_box: BuyBox;
}

// --- Match flow -----------------------------------------------------------

/**
 * Property deal input. Mirrors `PropertyInput`.
 * `Deal_ARV_Pct` is computed at match time and is never part of this shape.
 */
export interface PropertyInput {
  address: string;
  city: string;
  price: number;
  arv: number;
  beds: number | null;
  baths: number | null;
  sqft?: number | null;
  property_type: PropertyType;
  condition: Condition;
}

/** Plain-English fit/risk explanations attached to a match. Mirrors `MatchReasons`. */
export interface MatchReasons {
  fit: string[];
  risk: string[];
}

/** One ranked match. Mirrors `MatchItem`. */
export interface MatchItem {
  buyer_id: string;
  name: string;
  score: number;
  reasons: MatchReasons;
}

/** Success response (200) from `POST /match`. Mirrors `MatchResponse`. */
export interface MatchResponse {
  property_id: string;
  matches: MatchItem[];
}

// --- Message draft --------------------------------------------------------

/** Success response (200) from `POST /match/{buyer_id}/message`. Mirrors `MessageDraft`. */
export interface MessageDraft {
  channel: "sms";
  text: string;
}
