// # Feature: buybox-matcher, Property 19: Score color-tier mapping
import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { scoreTier } from "./helpers";

// Property 19: Score color-tier mapping (Validates: Requirements 13.5, 13.6, 13.7)
//
// For any integer score in [0, 100], the displayed tier is:
//   - "green" if score >= 80
//   - "amber" if 50 <= score <= 79
//   - "gray"  if score < 50
// The tiers partition the range with no overlap and no gap: every score maps to
// exactly one tier, and that tier matches the expected partition boundary.

describe("Property 19: Score color-tier mapping", () => {
  it("maps every integer score in [0,100] to the expected partition tier", () => {
    fc.assert(
      fc.property(fc.integer({ min: 0, max: 100 }), (score) => {
        const tier = scoreTier(score);

        const expected =
          score >= 80 ? "green" : score >= 50 ? "amber" : "gray";

        expect(tier).toBe(expected);
      }),
      { numRuns: 200 },
    );
  });

  it("produces tiers that partition [0,100] with no overlap or gap", () => {
    fc.assert(
      fc.property(fc.integer({ min: 0, max: 100 }), (score) => {
        const tier = scoreTier(score);

        // Exactly one tier applies to any score (totality + mutual exclusion).
        const isGreen = tier === "green";
        const isAmber = tier === "amber";
        const isGray = tier === "gray";
        const matchCount = Number(isGreen) + Number(isAmber) + Number(isGray);
        expect(matchCount).toBe(1);

        // Each tier corresponds to its disjoint, contiguous score band.
        if (isGreen) {
          expect(score).toBeGreaterThanOrEqual(80);
        } else if (isAmber) {
          expect(score).toBeGreaterThanOrEqual(50);
          expect(score).toBeLessThanOrEqual(79);
        } else {
          expect(score).toBeLessThan(50);
        }
      }),
      { numRuns: 200 },
    );
  });
});
