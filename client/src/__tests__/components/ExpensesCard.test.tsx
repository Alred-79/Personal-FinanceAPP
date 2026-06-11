import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/store/store", () => ({ useStore: vi.fn() }));

import ExpensesCard from "@/components/custom/Overview/ExpensesCard";
import { useStore } from "@/store/store";

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
    (useStore as ReturnType<typeof vi.fn>).mockReturnValue({ budgets: [] });
  });

  it("renders without crashing with empty budgets", () => {
    render(<ExpensesCard />);
    expect(screen.getByText(/no budgets configured/i)).toBeInTheDocument();
  });

  it("shows empty state text when budgets array is empty", () => {
    render(<ExpensesCard />);
    expect(screen.getByText("-- no budgets configured --")).toBeInTheDocument();
  });

  it("renders chart title when budgets have data", () => {
    (useStore as ReturnType<typeof vi.fn>).mockReturnValue({
      budgets: [mockBudget()],
    });
    render(<ExpensesCard />);
    expect(screen.getByText(/budget status/i)).toBeInTheDocument();
  });

  it("renders a recharts svg when budgets are present", () => {
    (useStore as ReturnType<typeof vi.fn>).mockReturnValue({
      budgets: [mockBudget()],
    });
    const { container } = render(<ExpensesCard />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("shows over-budget indicator for over_budget items", () => {
    (useStore as ReturnType<typeof vi.fn>).mockReturnValue({
      budgets: [mockBudget({ category: "Fun", spent: 120, effective_limit: 50, over_budget: true, on_pace: false, remaining: -70 })],
    });
    render(<ExpensesCard />);
    expect(screen.getByText(/over budget/i)).toBeInTheDocument();
  });

  it("does not show over-budget indicator when all budgets are on pace", () => {
    (useStore as ReturnType<typeof vi.fn>).mockReturnValue({
      budgets: [mockBudget({ over_budget: false })],
    });
    render(<ExpensesCard />);
    expect(screen.queryByText(/over budget/i)).toBeNull();
  });
});
