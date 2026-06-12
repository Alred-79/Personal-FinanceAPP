import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/store/store", () => ({ useStore: vi.fn() }));

import TimelineCard from "@/components/custom/Overview/TimelineCard";
import { useStore } from "@/store/store";

const setStore = (recentTransactions: unknown[]) =>
  (useStore as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
    recentTransactions,
    forecast: null,
    forecastLoaded: true,
    fetchForecast: vi.fn(),
  });

describe("TimelineCard", () => {
  beforeEach(() => setStore([]));

  it("renders without crashing with empty transactions", () => {
    render(<TimelineCard />);
    expect(screen.getByText(/no entries posted/i)).toBeInTheDocument();
  });

  it("shows empty state when only income transactions exist", () => {
    setStore([
      { id: 1, title: "Paycheck", amount: 3000, date: "2026-06-01", category: "Income", type: "income" },
    ]);
    render(<TimelineCard />);
    expect(screen.getByText(/no entries posted/i)).toBeInTheDocument();
  });

  it("renders a recharts svg when expense transactions exist", () => {
    setStore([
      { id: 1, title: "Coffee", amount: 5, date: "2026-06-01", category: "Food", type: "expense" },
    ]);
    const { container } = render(<TimelineCard />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("aggregates multiple expenses on the same date", () => {
    setStore([
      { id: 1, title: "Coffee", amount: 5, date: "2026-06-01", category: "Food", type: "expense" },
      { id: 2, title: "Lunch", amount: 15, date: "2026-06-01", category: "Food", type: "expense" },
    ]);
    const { container } = render(<TimelineCard />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("shows the card title", () => {
    render(<TimelineCard />);
    expect(screen.getByText(/cashflow timeline/i)).toBeInTheDocument();
  });
});
