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

export default function MatchPage() {
  // `null` => the form has not been submitted yet; an array => last successful
  // response (possibly empty, which triggers the empty-results message).
  const [matches, setMatches] = useState<MatchItem[] | null>(null);
  const [matchLoading, setMatchLoading] = useState(false);
  const [matchError, setMatchError] = useState<string | null>(null);

  // Draft state keyed by buyer_id so each MatchRow gets only its own draft.
  const [drafts, setDrafts] = useState<Record<string, DraftState>>({});

  // A draft request in flight must also disable the Find Buyers control (13.10).
  const anyDraftLoading = Object.values(drafts).some((d) => d.loading);
  const submitting = matchLoading || anyDraftLoading;

  async function handleSubmit(property: PropertyInput) {
    setMatchLoading(true);
    setMatchError(null);
    try {
      const response = await matchProperty(property);
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

      <PropertyForm onSubmit={handleSubmit} submitting={submitting} />

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
