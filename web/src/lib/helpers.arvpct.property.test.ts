import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { computeArvPct } from "./helpers";

// # Feature: buybox-matcher, Property 18: ARV% display computation
//
// Property 18 (Validates: Requirements 13.2):
//   For price > 0 and arv > 0, the computed Deal_ARV_Pct equals
//   `price / arv * 100` rounded to one decimal place.
//
// The expected value is computed independently of the helper and compared
// against `computeArvPct`'s output across >= 100 generated input pairs.

describe("Property 18: ARV% display computation", () => {
  it("equals price/arv*100 rounded to one decimal for positive finite inputs", () => {
    // Constrain to strictly-positive, finite magnitudes whose ratio stays
    // finite so the displayed percentage is always a well-defined number.
    const positive = fc.double({
      min: 0.01,
      max: 1e7,
      noNaN: true,
      noDefaultInfinity: true,
    });

    fc.assert(
      fc.property(positive, positive, (price, arv) => {
        const expected = Math.round((price / arv) * 100 * 10) / 10;
        const actual = computeArvPct(price, arv);

        // A valid percentage is produced (never null) for positive inputs.
        expect(actual).not.toBeNull();
        // The helper matches the independently rounded one-decimal value.
        expect(actual).toBe(expected);
        // The result carries at most one decimal place.
        expect(Math.round((actual as number) * 10)).toBe((actual as number) * 10);
      }),
      { numRuns: 200 },
    );
  });
});
