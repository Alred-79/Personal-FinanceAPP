import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import CashflowCalendar from "@/components/custom/CashflowCalendar/CashflowCalendar";
import type { Forecast } from "@/store/store";

const forecast: Forecast = {
  horizon_start: "2026-03-01",
  horizon_end: "2026-03-31",
  starting_balance: 1000,
  ending_balance: 1600,
  lowest_balance: 900,
  lowest_date: "2026-03-05",
  total_projected_expenses: 400,
  total_projected_income: 1000,
  will_go_negative: false,
  timeline: [
    { date: "2026-03-01", balance: 1000, change: 0, label: "Starting balance" },
    {
      date: "2026-03-05",
      balance: 900,
      change: -100,
      income: 0,
      expenses: 100,
      label: "Projected recurring cashflow",
    },
    {
      date: "2026-03-15",
      balance: 1900,
      change: 1000,
      income: 1000,
      expenses: 0,
      label: "Projected recurring cashflow",
    },
  ],
};

describe("CashflowCalendar", () => {
  it("renders the month label from the horizon start", () => {
    render(<CashflowCalendar forecast={forecast} />);
    expect(screen.getByText(/march 2026/i)).toBeInTheDocument();
  });

  it("renders a day cell for every day of the month", () => {
    render(<CashflowCalendar forecast={forecast} />);
    expect(screen.getByText("31")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("stamps projected flows on their days with sign", () => {
    render(<CashflowCalendar forecast={forecast} />);
    // -100 on 3/5 renders as −100; +1000 on 3/15 compacts to +1.0k.
    expect(screen.getByText(/−100/)).toBeInTheDocument();
    expect(screen.getByText(/\+1\.0k/)).toBeInTheDocument();
  });

  it("skips the synthetic zero-change starting point", () => {
    render(<CashflowCalendar forecast={forecast} />);
    expect(screen.queryByText(/−0$/)).toBeNull();
  });
});
