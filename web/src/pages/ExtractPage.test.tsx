import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ExtractPage from "./ExtractPage";
import { ApiError, extractBuyBox } from "../lib/api";
import type { ExtractResponse } from "../types";

/**
 * Component tests for ExtractPage (Extract_Screen), covering Requirement 12:
 *  - 12.3 chips render on a successful extraction (BuyBoxCard shown)
 *  - 12.4 a loading indicator shows and Extract is disabled while in flight
 *  - 12.5 a whitespace-only/empty message blocks submit and shows the required
 *         message (the API is never called)
 *  - 12.6 a save confirmation is shown on success
 *  - 12.7 a 422 shows "could not be parsed" and retains entered values
 *
 * The typed API client (`lib/api.ts`) is mocked so no real network calls are
 * made. The real `ApiError` class is preserved so the component's
 * `err instanceof ApiError` branch behaves exactly as in production.
 */

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return { ...actual, extractBuyBox: vi.fn() };
});

const extractBuyBoxMock = vi.mocked(extractBuyBox);

/** A representative successful extraction response. */
const sampleResponse: ExtractResponse = {
  buyer_id: "buyer-123",
  buy_box: {
    markets: ["Tampa", "Orlando"],
    strategy: "fix_and_flip",
    property_type: "single_family",
    price_min: 100_000,
    price_max: 250_000,
    arv_pct_max: 70,
    min_beds: 3,
    min_baths: 2,
    condition: "distressed",
  },
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ExtractPage", () => {
  it("renders extracted buy box chips on a successful response (12.3)", async () => {
    const user = userEvent.setup();
    extractBuyBoxMock.mockResolvedValueOnce(sampleResponse);

    render(<ExtractPage />);

    await user.type(
      screen.getByLabelText("Investor message"),
      "Looking for distressed SFH in Tampa under 250k, flip.",
    );
    await user.click(screen.getByRole("button", { name: "Extract" }));

    // The BuyBoxCard renders with the returned buy_box (aria-label is its hook).
    const card = await screen.findByLabelText("Extracted buy box");
    expect(card).toBeInTheDocument();
    // A couple of representative chip values from the returned buy box.
    expect(card).toHaveTextContent("Tampa, Orlando");
    expect(card).toHaveTextContent("Fix and flip");
    expect(extractBuyBoxMock).toHaveBeenCalledTimes(1);
  });

  it("disables Extract and shows a loading indicator while a request is in flight (12.4)", async () => {
    const user = userEvent.setup();
    // A pending promise that never resolves during the test keeps the page
    // in its in-flight state so we can assert on the loading UI.
    let resolve: ((value: ExtractResponse) => void) | undefined;
    extractBuyBoxMock.mockReturnValueOnce(
      new Promise<ExtractResponse>((res) => {
        resolve = res;
      }),
    );

    render(<ExtractPage />);

    await user.type(screen.getByLabelText("Investor message"), "Tampa flips");
    await user.click(screen.getByRole("button", { name: "Extract" }));

    // Button now reads "Extracting…" and is disabled; loading status shown.
    const button = screen.getByRole("button", { name: "Extracting…" });
    expect(button).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Extracting buy box…");

    // Resolve to let the component settle and avoid an act() warning.
    resolve?.(sampleResponse);
    await screen.findByLabelText("Extracted buy box");
  });

  it("blocks submission for a whitespace-only message and shows the required error (12.5)", async () => {
    const user = userEvent.setup();

    render(<ExtractPage />);

    await user.type(screen.getByLabelText("Investor message"), "   ");
    await user.click(screen.getByRole("button", { name: "Extract" }));

    expect(screen.getByText("A message is required.")).toBeInTheDocument();
    expect(extractBuyBoxMock).not.toHaveBeenCalled();
  });

  it("blocks submission for an empty message and never calls the API (12.5)", async () => {
    const user = userEvent.setup();

    render(<ExtractPage />);

    await user.click(screen.getByRole("button", { name: "Extract" }));

    expect(screen.getByText("A message is required.")).toBeInTheDocument();
    expect(extractBuyBoxMock).not.toHaveBeenCalled();
  });

  it("shows the parse-failure message and retains entered values on HTTP 422 (12.7)", async () => {
    const user = userEvent.setup();
    extractBuyBoxMock.mockRejectedValueOnce(
      new ApiError("http", "unparseable", { status: 422 }),
    );

    render(<ExtractPage />);

    const messageValue = "Gibberish that cannot be parsed";
    const nameValue = "Jane Investor";
    const companyValue = "Acme Capital";

    await user.type(screen.getByLabelText("Investor message"), messageValue);
    await user.type(screen.getByLabelText(/Buyer name/), nameValue);
    await user.type(screen.getByLabelText(/Company/), companyValue);
    await user.click(screen.getByRole("button", { name: "Extract" }));

    // Parse-specific error message is displayed.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "The message could not be parsed into a buy box. Edit it and try again.",
    );

    // All entered values are retained verbatim.
    expect(screen.getByLabelText("Investor message")).toHaveValue(messageValue);
    expect(screen.getByLabelText(/Buyer name/)).toHaveValue(nameValue);
    expect(screen.getByLabelText(/Company/)).toHaveValue(companyValue);

    // No success artifacts rendered.
    expect(screen.queryByText("Buyer saved.")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Extracted buy box")).not.toBeInTheDocument();
  });

  it("shows a save confirmation on a successful save (12.6)", async () => {
    const user = userEvent.setup();
    extractBuyBoxMock.mockResolvedValueOnce(sampleResponse);

    render(<ExtractPage />);

    await user.type(
      screen.getByLabelText("Investor message"),
      "Tampa flips under 250k",
    );
    await user.click(screen.getByRole("button", { name: "Extract" }));

    await waitFor(() => {
      expect(screen.getByText("Buyer saved.")).toBeInTheDocument();
    });
  });
});
