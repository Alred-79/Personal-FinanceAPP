import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/store/store", () => ({ useStore: vi.fn() }));
// The settings dialog pulls in the store + toast; stub it to a noop so this
// test stays focused on the gauge.
vi.mock("@/components/custom/SpendSettingsDialog/SpendSettingsDialog", () => ({
  SpendSettingsDialog: () => null,
}));

import SpendCard from "@/components/custom/Overview/SpendCard";
import { useStore } from "@/store/store";

const setStore = (overrides: Record<string, unknown>) =>
  (useStore as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
    spendOverTime: 0,
    budgetAllotment: 0,
    safeToSpend: null,
    warningPosition: 80,
    savingsPercent: 0,
    fixedPerMonth: 0,
    ...overrides,
  });

describe("SpendCard", () => {
  beforeEach(() => setStore({}));

  it("renders the card title", () => {
    render(<SpendCard />);
    expect(screen.getAllByText(/safe to spend/i).length).toBeGreaterThan(0);
  });

  it("shows the safe-to-spend label", () => {
    setStore({ spendOverTime: 250, budgetAllotment: 500 });
    render(<SpendCard />);
    expect(screen.getAllByText(/safe to spend/i).length).toBeGreaterThan(0);
  });

  it("displays the budget allotment in the footer", () => {
    setStore({ spendOverTime: 100, budgetAllotment: 400 });
    render(<SpendCard />);
    expect(screen.getByText(/\$400\.00/)).toBeInTheDocument();
  });

  it("shows 50% when spend is half of budget", () => {
    setStore({ spendOverTime: 50, budgetAllotment: 100 });
    render(<SpendCard />);
    expect(screen.getByText(/50%/)).toBeInTheDocument();
  });

  it("flags over-budget spending", () => {
    setStore({ spendOverTime: 150, budgetAllotment: 100 });
    render(<SpendCard />);
    expect(screen.getByText(/over/i)).toBeInTheDocument();
  });

  it("does not flag over-budget when within budget", () => {
    setStore({ spendOverTime: 80, budgetAllotment: 100 });
    render(<SpendCard />);
    expect(screen.queryByText(/over/i)).toBeNull();
  });

  it("renders a gauge svg", () => {
    setStore({ spendOverTime: 0, budgetAllotment: 0 });
    const { container } = render(<SpendCard />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });
});
