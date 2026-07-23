import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const state = {
  forecastLoaded: true,
  fetchForecast: vi.fn(),
  forecast: {
    events: [
      {
        date: "2026-08-01",
        income: 2000,
        expenses: 1500,
        net: 500,
        label: "Paycheck, Rent",
      },
    ],
  },
};

vi.mock("@/store/store", () => ({ useStore: () => state }));

import ForecastCard from "@/components/custom/Overview/ForecastCard";

afterEach(cleanup);

describe("Overview next cash events", () => {
  it("shows same-day income and obligations independently instead of netting the bill away", () => {
    render(
      <MemoryRouter>
        <ForecastCard />
      </MemoryRouter>
    );
    expect(screen.getByText("+$2,000.00 in")).toBeInTheDocument();
    expect(screen.getByText("−$1,500.00 out")).toBeInTheDocument();
    expect(screen.queryByText("+$500.00")).not.toBeInTheDocument();
  });
});
