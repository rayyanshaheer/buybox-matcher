import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, within, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MatchRow from "./MatchRow";
import type { MatchItem } from "../types";

// Component tests for MatchRow covering Requirements 13.5, 13.6, 13.7 (score
// color tiers), 13.8 (fit/risk chip styles), and 13.9 (draft modal "not sent"
// label + draft text). MatchRow is presentational so these tests need no API
// mock; the draft fetch is driven through the `onRequestDraft` callback and the
// returned text is fed back via the `draftText` prop.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function makeMatch(overrides: Partial<MatchItem> = {}): MatchItem {
  return {
    buyer_id: "buyer-1",
    name: "Acme Capital",
    score: 92,
    reasons: {
      fit: ["Market match: Tampa", "Price within range"],
      risk: ["ARV slightly above ceiling"],
    },
    ...overrides,
  };
}

describe("MatchRow score color tiers (13.5, 13.6, 13.7)", () => {
  it("renders the green tier when score >= 80", () => {
    render(<MatchRow match={makeMatch({ score: 80 })} onRequestDraft={vi.fn()} />);
    expect(screen.getByLabelText("Score 80")).toHaveAttribute("data-tier", "green");
  });

  it("renders the amber tier when score is between 50 and 79 inclusive", () => {
    const { rerender } = render(
      <MatchRow match={makeMatch({ score: 50 })} onRequestDraft={vi.fn()} />,
    );
    expect(screen.getByLabelText("Score 50")).toHaveAttribute("data-tier", "amber");

    rerender(<MatchRow match={makeMatch({ score: 79 })} onRequestDraft={vi.fn()} />);
    expect(screen.getByLabelText("Score 79")).toHaveAttribute("data-tier", "amber");
  });

  it("renders the gray tier when score < 50", () => {
    render(<MatchRow match={makeMatch({ score: 49 })} onRequestDraft={vi.fn()} />);
    expect(screen.getByLabelText("Score 49")).toHaveAttribute("data-tier", "gray");
  });
});

describe("MatchRow fit/risk chips (13.4, 13.8)", () => {
  it("renders fit reasons as green fit chips and risk reasons as amber risk chips", () => {
    const match = makeMatch({
      reasons: {
        fit: ["Market match: Tampa", "Strategy fit"],
        risk: ["Beds below minimum"],
      },
    });
    render(<MatchRow match={match} onRequestDraft={vi.fn()} />);

    const fitChips = screen.getAllByText(
      (_content, el) => el?.getAttribute("data-chip") === "fit",
    );
    const riskChips = screen.getAllByText(
      (_content, el) => el?.getAttribute("data-chip") === "risk",
    );

    expect(fitChips).toHaveLength(2);
    expect(riskChips).toHaveLength(1);

    // Fit chips carry the green style; risk chips carry the amber style.
    fitChips.forEach((chip) => expect(chip.className).toMatch(/green/));
    riskChips.forEach((chip) => expect(chip.className).toMatch(/amber/));

    expect(fitChips[0]).toHaveTextContent("Market match: Tampa");
    expect(riskChips[0]).toHaveTextContent("Beds below minimum");
  });
});

describe("MatchRow draft modal (13.9)", () => {
  it("requests a draft and opens a modal labeled 'not sent' showing the draft text", async () => {
    const user = userEvent.setup();
    const onRequestDraft = vi.fn();
    const draftText = "Hi! I have a Tampa deal at 123 Main St you may want.";

    render(
      <MatchRow
        match={makeMatch()}
        onRequestDraft={onRequestDraft}
        draftText={draftText}
      />,
    );

    // The modal is not present until the draft control is activated.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Draft message" }));

    expect(onRequestDraft).toHaveBeenCalledWith("buyer-1");

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("not sent")).toBeInTheDocument();
    expect(within(dialog).getByText(draftText)).toBeInTheDocument();
  });

  it("shows the loading state inside the modal while a draft is in progress", async () => {
    const user = userEvent.setup();
    render(
      <MatchRow match={makeMatch()} onRequestDraft={vi.fn()} draftLoading />,
    );

    await user.click(screen.getByRole("button", { name: "Draft message" }));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Generating draft…")).toBeInTheDocument();
    expect(within(dialog).getByText("not sent")).toBeInTheDocument();
  });
});
