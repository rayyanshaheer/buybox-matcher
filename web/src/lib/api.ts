/**
 * Typed fetch client for the BuyBox Matcher backend.
 *
 * Requirement 14.2: the frontend's ONLY configured external reference is
 * `VITE_API_URL`. This module reads no AI provider keys, no database
 * credentials, and no other secrets. All backend access flows through here.
 *
 * Responsibilities:
 *  - Resolve the API base URL from `VITE_API_URL`.
 *  - Apply a centralized request timeout (via `AbortController`).
 *  - Normalize all failures (HTTP errors, network errors, timeouts, malformed
 *    JSON) into a single `ApiError` shape so callers handle one error type.
 */

import type {
  ExtractRequest,
  ExtractResponse,
  BuyerListItem,
  PropertyInput,
  MatchResponse,
  MessageDraft,
} from "../types";

/** Default request timeout in milliseconds. */
export const DEFAULT_TIMEOUT_MS = 60_000;

/**
 * Normalized error raised by every client function. Callers can branch on
 * `kind` to render the right message without parsing raw responses.
 */
export class ApiError extends Error {
  /** Categorized failure cause. */
  readonly kind: "timeout" | "network" | "http" | "parse";
  /** HTTP status code when `kind === "http"`, otherwise `null`. */
  readonly status: number | null;
  /** Parsed error body from the backend, when available. */
  readonly body: unknown;

  constructor(
    kind: ApiError["kind"],
    message: string,
    options: { status?: number | null; body?: unknown } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = options.status ?? null;
    this.body = options.body ?? null;
  }
}

/**
 * Resolve the configured API base URL with a trailing slash stripped.
 * Throws an `ApiError` if `VITE_API_URL` is not configured so the failure is
 * surfaced clearly rather than producing requests to a relative path.
 */
function getBaseUrl(): string {
  const base = import.meta.env.VITE_API_URL;
  if (!base || base.trim() === "") {
    throw new ApiError(
      "network",
      "VITE_API_URL is not configured. Set it in the frontend environment.",
    );
  }
  return base.replace(/\/+$/, "");
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  /** Query string parameters; `null`/`undefined` values are omitted. */
  query?: Record<string, string | number | null | undefined>;
  /** Per-request timeout override in milliseconds. */
  timeoutMs?: number;
  /** Additional headers to include in the request. */
  extraHeaders?: Record<string, string>;
}

function buildUrl(
  path: string,
  query?: RequestOptions["query"],
): string {
  const base = getBaseUrl();
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const url = new URL(`${base}${normalizedPath}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== null && value !== undefined) {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

/**
 * Core request helper. Performs the fetch with a timeout, then normalizes the
 * outcome into either a typed result `T` or a thrown `ApiError`.
 */
async function request<T>(
  path: string,
  { method = "GET", body, query, timeoutMs = DEFAULT_TIMEOUT_MS, extraHeaders }: RequestOptions = {},
): Promise<T> {
  const url = buildUrl(path, query);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  const headers: Record<string, string> = {
    ...extraHeaders,
  };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError("timeout", `Request to ${path} timed out after ${timeoutMs}ms.`);
    }
    throw new ApiError("network", `Network error requesting ${path}.`);
  } finally {
    clearTimeout(timer);
  }

  // Parse JSON defensively; some responses (or errors) may not carry a body.
  let payload: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      if (response.ok) {
        throw new ApiError("parse", `Malformed JSON response from ${path}.`, {
          status: response.status,
        });
      }
    }
  }

  if (!response.ok) {
    throw new ApiError("http", `Request to ${path} failed with status ${response.status}.`, {
      status: response.status,
      body: payload,
    });
  }

  return payload as T;
}

// --- API Key Management (BYOK) -------------------------------------------

const API_KEY_STORAGE_KEY = "buybox_openai_key";

/** Get the user's stored OpenAI API key from localStorage. */
export function getStoredApiKey(): string | null {
  try {
    return localStorage.getItem(API_KEY_STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Save the user's OpenAI API key to localStorage. */
export function setStoredApiKey(key: string): void {
  try {
    localStorage.setItem(API_KEY_STORAGE_KEY, key);
  } catch {
    // Silent fail in environments without localStorage.
  }
}

/** Remove the user's stored OpenAI API key. */
export function clearStoredApiKey(): void {
  try {
    localStorage.removeItem(API_KEY_STORAGE_KEY);
  } catch {
    // Silent fail.
  }
}

// --- Endpoint wrappers ----------------------------------------------------

/** `POST /buy-boxes/extract` — extract a buy box and save a buyer. */
export function extractBuyBox(
  payload: ExtractRequest,
  timeoutMs?: number,
): Promise<ExtractResponse> {
  const extraHeaders: Record<string, string> = {};
  const apiKey = getStoredApiKey();
  if (apiKey) {
    extraHeaders["X-OpenAI-Key"] = apiKey;
  }
  return request<ExtractResponse>("/buy-boxes/extract", {
    method: "POST",
    body: payload,
    timeoutMs,
    extraHeaders,
  });
}

/** `GET /buyers` — list saved buyers with their buy boxes. */
export function listBuyers(timeoutMs?: number): Promise<BuyerListItem[]> {
  return request<BuyerListItem[]>("/buyers", { timeoutMs });
}

/** `POST /match` — score a property against every saved buyer. */
export function matchProperty(
  property: PropertyInput,
  params: { minScore?: number; limit?: number } = {},
  timeoutMs?: number,
): Promise<MatchResponse> {
  return request<MatchResponse>("/match", {
    method: "POST",
    body: property,
    query: { min_score: params.minScore, limit: params.limit },
    timeoutMs,
  });
}

/** `POST /match/{buyer_id}/message` — generate a first-touch SMS draft. */
export function draftMessage(
  buyerId: string,
  timeoutMs?: number,
): Promise<MessageDraft> {
  return request<MessageDraft>(`/match/${encodeURIComponent(buyerId)}/message`, {
    method: "POST",
    timeoutMs,
  });
}

/** `GET /health` — backend liveness check. */
export function health(timeoutMs?: number): Promise<{ status: string }> {
  return request<{ status: string }>("/health", { timeoutMs });
}
