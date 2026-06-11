import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { cleanup } from "@testing-library/react";
import PropertyForm from "./PropertyForm";
import type { PropertyInput } from "../types";

// Component tests for PropertyForm covering Requirements 13.1, 13.2, 13.3.

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("PropertyForm", () => {
  it("renders all required fields and controls (13.1)", () => {
    render(<PropertyForm onSubmit={vi.fn()} />);
    expect(screen.getByLabelText("Address")).toBeInTheDocument();
    expect(screen.getByLabelText("City")).toBeInTheDocument();
    expect(screen.getByLabelText("Price")).toBeInTheDocument();
    expect(screen.getByLabelText("ARV")).toBeInTheDocument();
    expect(screen.getByLabelText("Beds")).toBeInTheDocument();
    expect(screen.getByLabelText("Baths")).toBeInTheDocument();
    expect(screen.getByLabelText("Property type")).toBeInTheDocument();
    expect(screen.getByLabelText("Condition")).toBeInTheDocument();
  });

  it("displays live Deal_ARV_Pct to one decimal while price>0 and arv>0 (13.2)", async () => {
    const user = userEvent.setup();
    render(<PropertyForm onSubmit={vi.fn()} />);

    await user.type(screen.getByLabelText("Price"), "150000");
    await user.type(screen.getByLabelText("ARV"), "200000");

    // 150000 / 200000 * 100 = 75.0
    expect(screen.getByTestId("deal-arv-pct")).toHaveTextContent("75.0%");
  });

  it("suppresses Deal_ARV_Pct while arv is empty or 0 (13.3)", async () => {
    const user = userEvent.setup();
    render(<PropertyForm onSubmit={vi.fn()} />);

    await user.type(screen.getByLabelText("Price"), "150000");
    expect(screen.queryByTestId("deal-arv-pct")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("ARV"), "0");
    expect(screen.queryByTestId("deal-arv-pct")).not.toBeInTheDocument();
  });

  it("shows the arv validation message on submit when arv is empty/0 and does not submit (13.3)", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<PropertyForm onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText("Address"), "123 Main St");
    await user.type(screen.getByLabelText("City"), "Tampa");
    await user.type(screen.getByLabelText("Price"), "150000");
    await user.selectOptions(screen.getByLabelText("Property type"), "single_family");
    await user.selectOptions(screen.getByLabelText("Condition"), "distressed");

    await user.click(screen.getByRole("button", { name: "Find Buyers" }));

    expect(screen.getByRole("alert")).toHaveTextContent("arv must be greater than 0");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits the assembled PropertyInput when valid", async () => {
    const user = userEvent.setup();
    let received: PropertyInput | null = null;
    render(<PropertyForm onSubmit={(p) => (received = p)} />);

    await user.type(screen.getByLabelText("Address"), "123 Main St");
    await user.type(screen.getByLabelText("City"), "Tampa");
    await user.type(screen.getByLabelText("Price"), "150000");
    await user.type(screen.getByLabelText("ARV"), "200000");
    await user.type(screen.getByLabelText("Beds"), "3");
    await user.type(screen.getByLabelText("Baths"), "2");
    await user.selectOptions(screen.getByLabelText("Property type"), "single_family");
    await user.selectOptions(screen.getByLabelText("Condition"), "distressed");

    await user.click(screen.getByRole("button", { name: "Find Buyers" }));

    expect(received).toEqual({
      address: "123 Main St",
      city: "Tampa",
      price: 150000,
      arv: 200000,
      beds: 3,
      baths: 2,
      property_type: "single_family",
      condition: "distressed",
    });
  });
});
