import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/store/store", () => ({ useStore: vi.fn() }));
vi.mock("@/components/custom/SpendSettingsDialog/SpendSettingsDialog", () => ({
  SpendSettingsDialog: () => null,
}));

import SpendCard from "@/components/custom/Overview/SpendCard";
import { useStore } from "@/store/store";

const fetchSafeToSpend = vi.fn();
const ready = {
  available: 625,
  horizon_end: "2026-07-31",
  horizon_source: "paycheck",
  days_remaining: 8,
  daily_plan: 78.12,
  breakdown: {
    current_balance: 1_500,
    upcoming_bills: 500,
    projected_income: 200,
    goal_earmarks: 300,
    goal_contributions: 175,
    buffer: 100,
  },
  config: { horizon: "paycheck", include_income: true, include_goals: true, buffer: 100 },
  state: "ready",
  model_state: "scheduled_only",
  account_scope: {
    purpose: "near_term_cash",
    total_cents: 150_000,
    state: "ready",
    components: [{ account_id: 1, name: "Checking", role: "liquid_asset", currency: "USD", observed_at: null, signed_cents: 150_000, quality: "manual" }],
    exclusions: [],
  },
};

const setStore = (overrides: Record<string, unknown> = {}) =>
  (useStore as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
    safeToSpend: ready,
    safeToSpendStatus: "ready",
    fetchSafeToSpend,
    ...overrides,
  });

const renderCard = () => render(<MemoryRouter><SpendCard /></MemoryRouter>);

describe("SpendCard", () => {
  beforeEach(() => {
    fetchSafeToSpend.mockReset();
    setStore();
  });

  it("shows a loading state without inventing a fallback number", () => {
    setStore({ safeToSpend: null, safeToSpendStatus: "loading" });
    renderCard();
    expect(screen.getByText(/Calculating from your accounts/i)).toBeInTheDocument();
    expect(screen.queryByText("$1.00")).not.toBeInTheDocument();
  });

  it("preserves and labels a negative shortfall", () => {
    setStore({
      safeToSpend: {
        ...ready,
        available: -125,
        daily_plan: 0,
        is_negative: true,
        state: "ready_negative",
      },
    });
    renderCard();
    expect(screen.getByText("Shortfall")).toBeInTheDocument();
    expect(screen.getAllByText("-$125.00")).toHaveLength(2);
    expect(screen.queryByText("Daily ceiling")).not.toBeInTheDocument();
  });

  it("shows every term in the reconstructable equation", () => {
    renderCard();
    for (const label of ["Available cash", "Bills before horizon", "Income before horizon", "Already earmarked", "Goal contributions", "Safety buffer"]) {
      expect(screen.getByText(new RegExp(label, "i"))).toBeInTheDocument();
    }
  });

  it("labels limited account coverage and names exclusions", () => {
    setStore({
      safeToSpend: {
        ...ready,
        state: "limited",
        account_scope: {
          ...ready.account_scope,
          state: "limited",
          exclusions: [{ account_id: 2, name: "Travel Card", role: "liability", currency: "USD", observed_at: null, reason: "not_liquid_cash" }],
        },
      },
    });
    renderCard();
    expect(screen.getByText(/Limited account coverage/i)).toBeInTheDocument();
    expect(screen.getByText(/Travel Card: not liquid cash/i)).toBeInTheDocument();
  });

  it("does not present a probabilistic range for schedule-only data", () => {
    renderCard();
    expect(screen.getByText(/Scheduled cashflows only/i)).toBeInTheDocument();
    expect(screen.queryByText(/Modeled low-point range/i)).not.toBeInTheDocument();
  });
});
