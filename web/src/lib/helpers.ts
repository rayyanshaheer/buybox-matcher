/**
 * Shared pure helper functions for the BuyBox Matcher frontend.
 *
 * These helpers are intentionally free of React, DOM, and I/O so they can be
 * reused across screens and exhaustively exercised with property-based tests
 * (Tasks 9.3 and 9.4). Both screens (PropertyForm, MatchRow) consume them.
 */

/** Color tier for a match score badge. */
export type ScoreTier = "green" | "amber" | "gray";

/**
 * Compute the displayed Deal_ARV_Pct for the Match screen (Requirement 13.2).
 *
 * Deal_ARV_Pct = price / arv * 100, rounded to one decimal place.
 *
 * The value is only meaningful when both `price` and `arv` are greater than 0.
 * For any non-positive (or non-finite) input the function returns `null`, which
 * callers render as a suppressed value alongside the "arv must be greater than
 * 0" validation message (Requirement 13.3).
 *
 * @param price Property asking/contract price.
 * @param arv   Property after-repair value.
 * @returns The percentage rounded to one decimal, or `null` when not computable.
 */
export function computeArvPct(price: number, arv: number): number | null {
  if (!Number.isFinite(price) || !Number.isFinite(arv)) {
    return null;
  }
  if (price <= 0 || arv <= 0) {
    return null;
  }
  const pct = (price / arv) * 100;
  // Round to one decimal place.
  return Math.round(pct * 10) / 10;
}

/**
 * Map a match score to its color tier (Requirements 13.5, 13.6, 13.7).
 *
 * The partition is total and non-overlapping over [0, 100]:
 *  - score >= 80        -> "green"
 *  - 50 <= score <= 79  -> "amber"
 *  - score < 50         -> "gray"
 *
 * @param score Integer match score (0..100).
 * @returns The tier identifier used to style the score badge.
 */
export function scoreTier(score: number): ScoreTier {
  if (score >= 80) {
    return "green";
  }
  if (score >= 50) {
    return "amber";
  }
  return "gray";
}
