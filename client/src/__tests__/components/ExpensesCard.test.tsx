import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/store/store", () => ({ useStore: vi.fn() }));

import ExpensesCard from "@/components/custom/Overview/ExpensesCard";
import { useStore } from "@/store/store";

const renderCard = () =>
  render(
    <MemoryRouter>
      <ExpensesCard />
    </MemoryRouter>
  );

const mockBudget = (overrides = {}) => ({
  id: 1,
  category: "Food",
  monthly_limit: 100,
  effective_limit: 100,
  rollover: false,
  spent: 60,
  remaining: 40,
  prorated_target: 50,
  over_budget: false,
  on_pace: true,
  ...overrides,
});

describe("ExpensesCard", () => {
  beforeEach(() => {
    (useStore as unknown as ReturnType<typeof vi.fn>).mockReturnValue({ budgets: [] });
  });

  it("renders without crashing with empty budgets", () => {
    renderCard();
    expect(screen.getByText(/no budget envelopes/i)).toBeInTheDocument();
  });

  it("shows a prompt to create a budget when empty", () => {
    renderCard();
    expect(screen.getByText(/rule a budget/i)).toBeInTheDocument();
  });

  it("renders the card title when budgets have data", () => {
    (useStore as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      budgets: [mockBudget()],
    });
    renderCard();
    expect(screen.getByText(/budget status/i)).toBeInTheDocument();
  });

  it("renders each budget category when budgets are present", () => {
    (useStore as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      budgets: [mockBudget()],
    });
    renderCard();
    expect(screen.getByText("Food")).toBeInTheDocument();
  });

  it("shows over-budget indicator for over_budget items", () => {
    (useStore as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      budgets: [
        mockBudget({
          category: "Fun",
          spent: 120,
          effective_limit: 50,
          over_budget: true,
          on_pace: false,
          remaining: -70,
        }),
      ],
    });
    renderCard();
    expect(screen.getByText(/over/i)).toBeInTheDocument();
  });

  it("does not show over-budget indicator when all budgets are on pace", () => {
    (useStore as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      budgets: [mockBudget({ over_budget: false })],
    });
    renderCard();
    expect(screen.queryByText(/over budget/i)).toBeNull();
  });
});
