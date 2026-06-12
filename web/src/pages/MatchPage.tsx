/**
 * Match_Screen route (`/match`) — Requirements 13.4, 13.9, 13.10, 13.11, 13.12.
 *
 * Composes the reusable PropertyForm and MatchRow presentational components
 * with the typed API client (`lib/api.ts`) and owns all screen-level state:
 *
 *  - Submitting the property form issues `POST /match`; on success the returned
 *    matches are rendered as MatchRows ordered by descending score (13.4).
 *  - While a match request OR any draft request is in flight, the Find Buyers
 *    control is disabled and a loading indicator is shown (13.10) — realized by
 *    passing `submitting` to PropertyForm and rendering a status line.
 *  - On a failure or the client's centralized 10s timeout (both surface as an
 *    `ApiError`), an error message ("matches could not be retrieved") is shown,
 *    the form values are retained (PropertyForm keeps its own field state and
 *    is never unmounted), and the control is re-enabled (13.12).
 *  - A successful match response with zero rows shows the empty-results message
 *    "no buyers matched" (13.11).
 *  - Activating a row's draft control triggers `POST /match/{buyer_id}/message`;
 *    the resulting text/loading/error is fed back to that specific MatchRow via
 *    its `draftText` / `draftLoading` / `draftError` props (13.9).
 */
import { useState } from "react";
import PropertyForm from "../components/PropertyForm";
import MatchRow from "../components/MatchRow";
import { draftMessage, matchProperty } from "../lib/api";
import type { MatchItem, PropertyInput } from "../types";

/**
 * Single user-facing error string for match/draft failures and timeouts.
 * Requirement 13.12 specifies the message must indicate that matches could not
 * be retrieved; the same phrasing is reused for draft failures so both paths
 * surface a consistent, recognizable message.
 */
const ERROR_MESSAGE = "Matches could not be retrieved. Please try again.";

/** Per-buyer draft state fed back into the corresponding MatchRow. */
interface DraftState {
  loading: boolean;
  text: string | null;
  error: string | null;
}

/** Demo data: sample matches returned without hitting the backend. */
const DEMO_MATCHES: MatchItem[] = [
  {
    buyer_id: "demo-1",
    name: "Sarah Johnson",
    score: 92,
    reasons: {
      fit: ["Market match: Tampa", "Strategy match: fix_and_flip", "Price within range", "Property type match"],
      risk: ["ARV% slightly above threshold"],
    },
  },
  {
    buyer_id: "demo-2",
    name: "Mike Chen",
    score: 78,
    reasons: {
      fit: ["Market match: Tampa", "Price within range", "Beds/baths meet minimum"],
      risk: ["Strategy mismatch: buyer prefers buy_and_hold", "Condition mismatch"],
    },
  },
  {
    buyer_id: "demo-3",
    name: "Rodriguez Capital LLC",
    score: 65,
    reasons: {
      fit: ["Market match: Tampa", "Property type match"],
      risk: ["Price above buyer max", "ARV% exceeds ceiling"],
    },
  },
];

export default function MatchPage() {
  // `null` => the form has not been submitted yet; an array => last successful
  // response (possibly empty, which triggers the empty-results message).
  const [matches, setMatches] = useState<MatchItem[] | null>(null);
  const [matchLoading, setMatchLoading] = useState(false);
  const [matchError, setMatchError] = useState<string | null>(null);
  const [isDemo, setIsDemo] = useState(false);
  const [formKey, setFormKey] = useState(0);
  const [demoValues, setDemoValues] = useState<Record<string, string> | undefined>(undefined);

  // Draft state keyed by buyer_id so each MatchRow gets only its own draft.
  const [drafts, setDrafts] = useState<Record<string, DraftState>>({});

  // A draft request in flight must also disable the Find Buyers control (13.10).
  const anyDraftLoading = Object.values(drafts).some((d) => d.loading);
  const submitting = matchLoading || anyDraftLoading;

  function handleDemo() {
    setMatchError(null);
    setIsDemo(true);
    setDemoValues({
      address: "742 Palm Ave",
      city: "Tampa",
      price: "220000",
      arv: "310000",
      beds: "3",
      baths: "2",
      propertyType: "single_family",
      condition: "distressed",
    });
    setFormKey((k) => k + 1);
    setMatches(DEMO_MATCHES);
  }

  async function handleSubmit(property: PropertyInput) {
    setMatchLoading(true);
    setMatchError(null);
    setIsDemo(false);
    try {
      const response = await matchProperty(property, { limit: 10 });
      // Order rows by descending score (13.4); sort defensively rather than
      // assuming the backend ordering.
      const ordered = [...response.matches].sort((a, b) => b.score - a.score);
      setMatches(ordered);
    } catch {
      // The client normalizes every failure — HTTP errors, network failures,
      // and the centralized 10s timeout — into a thrown error (13.12). Retain
      // prior form values (PropertyForm is never unmounted) and show the error.
      setMatchError(ERROR_MESSAGE);
    } finally {
      setMatchLoading(false);
    }
  }

  async function handleRequestDraft(buyerId: string) {
    // In demo mode, return a fake draft instead of hitting the backend.
    if (isDemo) {
      setDrafts((prev) => ({
        ...prev,
        [buyerId]: { loading: true, text: null, error: null },
      }));
      setTimeout(() => {
        setDrafts((prev) => ({
          ...prev,
          [buyerId]: {
            loading: false,
            text: "Hey! I've got a property in Tampa that fits your buy box — distressed SFH, 3/2, listed at $220k. ARV is around $310k. Want me to send over the details?",
            error: null,
          },
        }));
      }, 800);
      return;
    }

    setDrafts((prev) => ({
      ...prev,
      [buyerId]: { loading: true, text: null, error: null },
    }));
    try {
      const draft = await draftMessage(buyerId);
      setDrafts((prev) => ({
        ...prev,
        [buyerId]: { loading: false, text: draft.text, error: null },
      }));
    } catch {
      // Draft failures/timeouts also surface the retrieval error (13.12); the
      // message is shown inside the row's modal via `draftError`.
      setDrafts((prev) => ({
        ...prev,
        [buyerId]: { loading: false, text: null, error: ERROR_MESSAGE },
      }));
    }
  }

  const showEmpty = matches !== null && matches.length === 0 && !matchLoading;

  return (
    <section className="flex flex-col gap-6">
      <div>
        <h2 className="text-lg font-medium">Match</h2>
        <p className="text-sm text-gray-500">
          Enter a property to score it against every saved buyer.
        </p>
      </div>

      {/* Demo banner for users without data */}
      {matches === null && !matchLoading && (
        <div className="rounded-md border border-blue-200 bg-blue-50 p-4">
          <p className="text-sm text-blue-800">
            <span className="font-medium">New here?</span> Try the demo to see
            how matching works — no API key or saved buyers needed.
          </p>
          <button
            onClick={handleDemo}
            className="mt-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Try Demo
          </button>
        </div>
      )}

      <PropertyForm key={formKey} onSubmit={handleSubmit} submitting={submitting} initialValues={demoValues} />

      {/* Loading indicator while a match/draft request is in progress (13.10). */}
      {submitting && (
        <p className="text-sm text-gray-600" role="status" aria-live="polite">
          {matchLoading ? "Finding buyers…" : "Generating draft…"}
        </p>
      )}

      {/* Match request / timeout failure message (13.12). */}
      {matchError !== null && (
        <p className="text-sm text-red-600" role="alert">
          {matchError}
        </p>
      )}

      {/* Empty-results message when a successful response has zero rows (13.11). */}
      {showEmpty && (
        <p className="text-sm text-gray-600">
          No buyers matched the submitted property.
        </p>
      )}

      {/* Ranked matches, descending by score (13.4). */}
      {matches !== null && matches.length > 0 && (
        <div className="flex flex-col gap-3">
          {isDemo && (
            <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              <span className="font-medium">Demo mode</span> — these are sample
              results. To use real data, add buyers via the{" "}
              <a href="/extract" className="underline">Extract</a> tab (requires
              an OpenAI key in{" "}
              <a href="/settings" className="underline">Settings</a>).
            </div>
          )}
          {matches.map((match) => {
            const draft = drafts[match.buyer_id];
            return (
              <MatchRow
                key={match.buyer_id}
                match={match}
                onRequestDraft={handleRequestDraft}
                draftText={draft?.text ?? null}
                draftLoading={draft?.loading ?? false}
                draftError={draft?.error ?? null}
              />
            );
          })}
        </div>
      )}
    </section>
  );
}
