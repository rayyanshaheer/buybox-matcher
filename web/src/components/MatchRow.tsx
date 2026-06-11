/**
 * MatchRow — renders one ranked match (Requirements 13.4-13.9).
 *
 * Per the design ("Frontend Components" → MatchRow), a row shows:
 *  - the numeric score in a badge whose color tier is derived from the shared
 *    `scoreTier` helper: >=80 green, 50-79 amber, <50 gray (13.5, 13.6, 13.7);
 *  - the buyer's fit reasons as green "fit" chips and risk reasons as amber
 *    "risk" chips (13.4, 13.8);
 *  - a draft-message control that opens a modal labeled "not sent" displaying
 *    the returned draft text (13.9).
 *
 * The draft flow is split so this component stays presentational: the actual
 * API call is owned by MatchPage (Task 11.3). MatchRow receives an
 * `onRequestDraft` callback to ask the parent to fetch a draft, plus the
 * resulting `draftText` (and optional loading/error state) as props. When the
 * user activates the draft control, MatchRow opens the modal and invokes the
 * callback; the parent performs the request and feeds the text back in.
 */
import { useState } from "react";
import type { MatchItem } from "../types";
import { scoreTier, type ScoreTier } from "../lib/helpers";

interface MatchRowProps {
  /** The ranked match to render. */
  match: MatchItem;
  /**
   * Ask the parent (MatchPage) to fetch a first-touch SMS draft for this
   * match's buyer. The parent performs the API call and returns the text via
   * the `draftText` prop. Called when the user activates the draft control.
   */
  onRequestDraft: (buyerId: string) => void;
  /**
   * The draft text returned by the parent for this row, or `null` when no
   * draft has been returned yet. Rendered inside the "not sent" modal.
   */
  draftText?: string | null;
  /** Whether a draft request for this row is in progress. */
  draftLoading?: boolean;
  /** An error message to show in the modal when the draft request failed. */
  draftError?: string | null;
}

/** Tailwind classes for the score badge, keyed by color tier. */
const BADGE_TIER_CLASSES: Record<ScoreTier, string> = {
  green: "bg-green-100 text-green-800 border-green-300",
  amber: "bg-amber-100 text-amber-800 border-amber-300",
  gray: "bg-gray-100 text-gray-700 border-gray-300",
};

export default function MatchRow({
  match,
  onRequestDraft,
  draftText = null,
  draftLoading = false,
  draftError = null,
}: MatchRowProps) {
  const [modalOpen, setModalOpen] = useState(false);

  const tier = scoreTier(match.score);

  function handleDraftClick() {
    setModalOpen(true);
    onRequestDraft(match.buyer_id);
  }

  return (
    <div
      className="flex flex-col gap-3 rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
      aria-label={`Match for ${match.name}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          {/* Score badge — color tier from the shared helper (13.5-13.7). */}
          <span
            className={`inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-full border text-lg font-bold ${BADGE_TIER_CLASSES[tier]}`}
            aria-label={`Score ${match.score}`}
            data-tier={tier}
          >
            {match.score}
          </span>
          <span className="font-medium text-gray-900">{match.name}</span>
        </div>

        <button
          type="button"
          onClick={handleDraftClick}
          className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Draft message
        </button>
      </div>

      {/* Fit chips — green style (13.4, 13.8). */}
      {match.reasons.fit.length > 0 && (
        <div className="flex flex-wrap gap-2" aria-label="Fit reasons">
          {match.reasons.fit.map((reason, i) => (
            <span
              key={`fit-${i}`}
              data-chip="fit"
              className="inline-flex items-center rounded-full border border-green-300 bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800"
            >
              {reason}
            </span>
          ))}
        </div>
      )}

      {/* Risk chips — amber style (13.4, 13.8). */}
      {match.reasons.risk.length > 0 && (
        <div className="flex flex-wrap gap-2" aria-label="Risk reasons">
          {match.reasons.risk.map((reason, i) => (
            <span
              key={`risk-${i}`}
              data-chip="risk"
              className="inline-flex items-center rounded-full border border-amber-300 bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800"
            >
              {reason}
            </span>
          ))}
        </div>
      )}

      {/* Draft modal labeled "not sent" (13.9). */}
      {modalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          role="dialog"
          aria-modal="true"
          aria-label={`Draft message for ${match.name}`}
        >
          <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="text-base font-semibold text-gray-900">
                Draft message
              </h2>
              {/* "not sent" label — message has not been transmitted (13.9). */}
              <span className="inline-flex items-center rounded-full border border-gray-300 bg-gray-100 px-2.5 py-0.5 text-xs font-medium uppercase tracking-wide text-gray-600">
                not sent
              </span>
            </div>

            <div className="min-h-[4rem] rounded-md border border-gray-200 bg-gray-50 p-3 text-sm text-gray-800">
              {draftLoading ? (
                <span className="text-gray-500">Generating draft…</span>
              ) : draftError ? (
                <span className="text-red-600">{draftError}</span>
              ) : draftText ? (
                <p className="whitespace-pre-wrap">{draftText}</p>
              ) : (
                <span className="text-gray-400">No draft available.</span>
              )}
            </div>

            <div className="mt-4 flex justify-end">
              <button
                type="button"
                onClick={() => setModalOpen(false)}
                className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
