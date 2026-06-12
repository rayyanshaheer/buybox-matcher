/**
 * Extract_Screen route (`/extract`).
 *
 * Lets a wholesaler paste a raw investor message (plus optional buyer name and
 * company), submit it to the extraction API, and review the structured Buy_Box
 * that comes back as labeled chips. Implements Requirement 12:
 *
 *  - 12.1 textarea (<=10,000 chars) + optional name/company inputs (<=100 each)
 *  - 12.2 activating Extract with a non-whitespace message submits to the API
 *  - 12.3 a successful response renders the Buy_Box via <BuyBoxCard/> chips
 *  - 12.4 while a request is in flight, a loading indicator shows and the
 *         Extract action is disabled
 *  - 12.5 a whitespace-only/empty message blocks submission and shows
 *         "a message is required"
 *  - 12.6 a successful save shows a confirmation (rendered synchronously on the
 *         same response tick, well within the 2s budget)
 *  - 12.7 a 422 response shows "could not be parsed" and retains every entered
 *         value (message, name, company)
 *
 * All backend access flows through the typed client in `lib/api.ts`; this page
 * holds no secrets and references no external URL of its own (Req 14.2).
 */
import { useState } from "react";
import { ApiError, extractBuyBox, getStoredApiKey } from "../lib/api";
import BuyBoxCard from "../components/BuyBoxCard";
import type { ExtractResponse } from "../types";

/** Field length limits from Requirement 12.1. */
const MAX_MESSAGE_CHARS = 10_000;
const MAX_NAME_CHARS = 100;
const MAX_COMPANY_CHARS = 100;

/** User-facing strings, kept as constants so tests can assert on them. */
const MSG_REQUIRED = "A message is required.";
const MSG_PARSE_FAILED =
  "The message could not be parsed into a buy box. Edit it and try again.";
const MSG_GENERIC_FAILED =
  "Something went wrong while extracting. Please try again.";
const MSG_SAVE_CONFIRM = "Buyer saved.";

export default function ExtractPage() {
  // Controlled form values (retained verbatim across a 422 per Req 12.7).
  const [message, setMessage] = useState("");
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");

  // Request lifecycle state.
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [result, setResult] = useState<ExtractResponse | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    // Req 12.5: block empty / whitespace-only messages before any request.
    if (message.trim() === "") {
      setValidationError(MSG_REQUIRED);
      setApiError(null);
      setResult(null);
      return;
    }

    // Clear stale feedback and enter the in-flight state (Req 12.4).
    setValidationError(null);
    setApiError(null);
    setResult(null);
    setIsSubmitting(true);

    try {
      // Req 12.2: submit the message (and optional, trimmed-empty -> null
      // name/company) to the extraction API.
      const response = await extractBuyBox({
        raw_text: message,
        name: name.trim() === "" ? null : name,
        company: company.trim() === "" ? null : company,
      });
      // Req 12.3 / 12.6: render chips and the save confirmation.
      setResult(response);
    } catch (err) {
      // Req 12.7: a 422 means the text could not be parsed; retain all values
      // (we never clear the inputs) and show the parse-specific message.
      if (err instanceof ApiError && err.kind === "http" && err.status === 422) {
        setApiError(MSG_PARSE_FAILED);
      } else {
        setApiError(MSG_GENERIC_FAILED);
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-lg font-medium">Extract a buy box</h2>
        <p className="text-sm text-gray-500">
          Paste an investor message to extract structured purchase criteria and
          save the buyer.
        </p>
      </div>

      {/* API key notice */}
      {!getStoredApiKey() && (
        <div className="rounded-md border border-yellow-200 bg-yellow-50 p-4">
          <p className="text-sm text-yellow-800">
            <span className="font-medium">API key required.</span> Extraction
            uses OpenAI to parse investor messages. Add your key in{" "}
            <a href="/settings" className="underline font-medium">Settings</a>{" "}
            to get started. Don't have one?{" "}
            <a
              href="https://platform.openai.com/api-keys"
              target="_blank"
              rel="noopener noreferrer"
              className="underline"
            >
              Get one from OpenAI
            </a>{" "}
            (requires a paid account, ~$5 minimum).
          </p>
          <p className="mt-2 text-sm text-yellow-700">
            Meanwhile, you can{" "}
            <a href="/match" className="underline font-medium">try the demo</a>{" "}
            on the Match page to see how the app works without an API key.
          </p>
        </div>
      )}

      <form className="space-y-4" onSubmit={handleSubmit} noValidate>
        <div>
          <label
            htmlFor="message"
            className="block text-sm font-medium text-gray-700"
          >
            Investor message
          </label>
          <textarea
            id="message"
            name="message"
            rows={8}
            maxLength={MAX_MESSAGE_CHARS}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            disabled={isSubmitting}
            aria-invalid={validationError !== null}
            aria-describedby={validationError ? "message-error" : undefined}
            placeholder="e.g. Looking for distressed single family homes in Tampa under $250k, flip strategy, ARV up to 70%..."
            className="mt-1 w-full rounded-md border border-gray-300 p-3 text-sm shadow-sm focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-500 disabled:bg-gray-100"
          />
          <div className="mt-1 flex items-center justify-between">
            {validationError ? (
              <p id="message-error" className="text-sm text-red-600">
                {validationError}
              </p>
            ) : (
              <span />
            )}
            <span className="text-xs text-gray-400">
              {message.length.toLocaleString("en-US")} /{" "}
              {MAX_MESSAGE_CHARS.toLocaleString("en-US")}
            </span>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label
              htmlFor="name"
              className="block text-sm font-medium text-gray-700"
            >
              Buyer name <span className="text-gray-400">(optional)</span>
            </label>
            <input
              id="name"
              name="name"
              type="text"
              maxLength={MAX_NAME_CHARS}
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isSubmitting}
              className="mt-1 w-full rounded-md border border-gray-300 p-2 text-sm shadow-sm focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-500 disabled:bg-gray-100"
            />
          </div>
          <div>
            <label
              htmlFor="company"
              className="block text-sm font-medium text-gray-700"
            >
              Company <span className="text-gray-400">(optional)</span>
            </label>
            <input
              id="company"
              name="company"
              type="text"
              maxLength={MAX_COMPANY_CHARS}
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              disabled={isSubmitting}
              className="mt-1 w-full rounded-md border border-gray-300 p-2 text-sm shadow-sm focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-500 disabled:bg-gray-100"
            />
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={isSubmitting}
            className="inline-flex items-center gap-2 rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-400"
          >
            {isSubmitting && (
              <span
                className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent"
                aria-hidden="true"
              />
            )}
            {isSubmitting ? "Extracting…" : "Extract"}
          </button>
          {isSubmitting && (
            <span role="status" className="text-sm text-gray-500">
              Extracting buy box…
            </span>
          )}
        </div>
      </form>

      {/* Req 12.7: parse / generic failure message. */}
      {apiError && (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          {apiError}
        </div>
      )}

      {/* Req 12.3 + 12.6: chips and save confirmation on success. */}
      {result && (
        <div className="space-y-3">
          <div
            role="status"
            className="rounded-md border border-green-200 bg-green-50 p-3 text-sm text-green-700"
          >
            {MSG_SAVE_CONFIRM}
          </div>
          <div>
            <h3 className="mb-2 text-sm font-medium text-gray-700">
              Extracted buy box
            </h3>
            <BuyBoxCard buyBox={result.buy_box} />
          </div>
        </div>
      )}
    </section>
  );
}
