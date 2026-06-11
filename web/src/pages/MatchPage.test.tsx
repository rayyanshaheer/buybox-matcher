import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MatchPage from "./MatchPage";
import type { MatchItem, MatchResponse, MessageDraft } from "../types";

// Component tests for MatchPage covering Requirements 13.4 (rows ordered by
// descending score), 13.9 (draft modal "not sent" + text), 13.10 (loading
// disables Find Buyers + status), 13.11 (empty-results message), and 13.12
// (error/timeout message, retained form, re-enabled control).
//
// The API client is mocked so the page logic is exercised in isolation; loading
// states are asserted against deferred promises that we resolve/reject manually.

vi.mock("../lib/api", () => ({
  matchProperty: vi.fn(),
  draftMessage: vi.fn(),
}));

import { matchProperty, draftMessage } from "../lib/api";

const matchPropertyMock = vi.mocked(matchProperty);
const draftMessageMock = vi.mocked(draftMessage);

/** A controllable promise so tests can assert on the in-flight loading state. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function makeMatch(overrides: Partial<MatchItem> = {}): MatchItem {
  return {
    buyer_id: "buyer-1",
    name: "Acme Capital",
    score: 70,
    reasons: { fit: ["Market match"], risk: ["Price near limit"] },
    ...overrides,
  };
}

/** Fill the PropertyForm with valid values and click Find Buyers. */
async function submitValidProperty(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Address"), "123 Main St");
  await user.type(screen.getByLabelText("City"), "Tampa");
  await user.type(screen.getByLabelText("Price"), "150000");
  await user.type(screen.getByLabelText("ARV"), "200000");
  await user.selectOptions(screen.getByLabelText("Property type"), "single_family");
  await user.selectOptions(screen.getByLabelText("Condition"), "distressed");
  await user.click(screen.getByRole("button", { name: "Find Buyers" }));
}

beforeEach(() => {
  matchPropertyMock.mockReset();
  draftMessageMock.mockReset();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("MatchPage match results (13.4)", () => {
  it("renders matches ordered by descending score", async () => {
    const user = userEvent.setup();
    const response: MatchResponse = {
      property_id: "prop-1",
      matches: [
        makeMatch({ buyer_id: "low", name: "Low Buyer", score: 40 }),
        makeMatch({ buyer_id: "high", name: "High Buyer", score: 95 }),
        makeMatch({ buyer_id: "mid", name: "Mid Buyer", score: 65 }),
      ],
    };
    matchPropertyMock.mockResolvedValue(response);

    render(<MatchPage />);
    await submitValidProperty(user);

    await waitFor(() =>
      expect(screen.getByLabelText("Match for High Buyer")).toBeInTheDocument(),
    );

    const rows = screen.getAllByLabelText(/^Match for /);
    expect(rows.map((r) => r.getAttribute("aria-label"))).toEqual([
      "Match for High Buyer",
      "Match for Mid Buyer",
      "Match for Low Buyer",
    ]);
  });
});

describe("MatchPage loading state (13.10)", () => {
  it("disables Find Buyers and shows a status while a match request is in flight", async () => {
    const user = userEvent.setup();
    const d = deferred<MatchResponse>();
    matchPropertyMock.mockReturnValue(d.promise);

    render(<MatchPage />);
    await submitValidProperty(user);

    const button = screen.getByRole("button", { name: /Finding/ });
    expect(button).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Finding buyers…");

    // Resolve and confirm the control re-enables afterward.
    d.resolve({ property_id: "p", matches: [] });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Find Buyers" })).toBeEnabled(),
    );
  });
});

describe("MatchPage empty results (13.11)", () => {
  it("shows the empty-results message when zero matches are returned", async () => {
    const user = userEvent.setup();
    matchPropertyMock.mockResolvedValue({ property_id: "p", matches: [] });

    render(<MatchPage />);
    await submitValidProperty(user);

    await waitFor(() =>
      expect(
        screen.getByText("No buyers matched the submitted property."),
      ).toBeInTheDocument(),
    );
  });
});

describe("MatchPage error/timeout state (13.12)", () => {
  it("shows the retrieval error, retains form values, and re-enables the control", async () => {
    const user = userEvent.setup();
    matchPropertyMock.mockRejectedValue(new Error("timeout"));

    render(<MatchPage />);
    await submitValidProperty(user);

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Matches could not be retrieved. Please try again.",
      ),
    );

    // Form values are retained (PropertyForm is never unmounted).
    expect(screen.getByLabelText("Address")).toHaveValue("123 Main St");
    expect(screen.getByLabelText("City")).toHaveValue("Tampa");

    // The Find Buyers control is re-enabled.
    expect(screen.getByRole("button", { name: "Find Buyers" })).toBeEnabled();
  });
});

describe("MatchPage draft flow (13.9)", () => {
  it("opens a 'not sent' modal with the drafted text when the draft control is used", async () => {
    const user = userEvent.setup();
    matchPropertyMock.mockResolvedValue({
      property_id: "p",
      matches: [makeMatch({ buyer_id: "buyer-1", name: "Acme Capital", score: 88 })],
    });
    const draft: MessageDraft = {
      channel: "sms",
      text: "Hi! Tampa deal at 123 Main St for you.",
    };
    draftMessageMock.mockResolvedValue(draft);

    render(<MatchPage />);
    await submitValidProperty(user);

    await waitFor(() =>
      expect(screen.getByLabelText("Match for Acme Capital")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: "Draft message" }));

    expect(draftMessageMock).toHaveBeenCalledWith("buyer-1");

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("not sent")).toBeInTheDocument();
    await waitFor(() =>
      expect(within(dialog).getByText(draft.text)).toBeInTheDocument(),
    );
  });
});
