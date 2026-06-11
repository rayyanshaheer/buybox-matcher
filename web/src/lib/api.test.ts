import { describe, it, expect, vi, afterEach } from "vitest";
import fc from "fast-check";
import { ApiError, health } from "./api";

// Smoke tests confirming the Vitest + fast-check harness is wired up and the
// API client's centralized error normalization behaves as designed. The full
// behavioral/property tests for screens live in later tasks (9.3, 9.4, 10.x).

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("api client error normalization", () => {
  it("normalizes a non-ok HTTP response into an ApiError with status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "boom" }), { status: 500 }),
      ),
    );
    await expect(health()).rejects.toMatchObject({
      name: "ApiError",
      kind: "http",
      status: 500,
    });
  });

  it("normalizes a thrown network failure into an ApiError (fast-check)", async () => {
    await fc.assert(
      fc.asyncProperty(fc.string(), async (msg) => {
        vi.stubGlobal(
          "fetch",
          vi.fn().mockRejectedValue(new TypeError(msg)),
        );
        const err = await health().catch((e) => e);
        expect(err).toBeInstanceOf(ApiError);
        expect(err.kind).toBe("network");
      }),
      { numRuns: 25 },
    );
  });
});
