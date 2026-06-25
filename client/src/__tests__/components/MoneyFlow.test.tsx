import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, waitFor, within } from "@testing-library/react";

const apiGet = vi.fn();
vi.mock("@/lib/api", () => ({
  default: {
    get: (...a: unknown[]) => apiGet(...a),
  },
}));

import MoneyFlow from "@/components/custom/MoneyFlow/MoneyFlow";

function mockAnalytics() {
  apiGet.mockImplementation((_url: string, opts: { params: { tx_type: string } }) => {
    if (opts.params.tx_type === "income") {
      return Promise.resolve({
        data: { totals_by_category: { Salary: 5000, Freelance: 1500 } },
      });
    }
    return Promise.resolve({
      data: { totals_by_category: { Rent: 2000, Food: 900, Transport: 400 } },
    });
  });
}

describe("MoneyFlow", () => {
  beforeEach(() => {
    apiGet.mockReset();
  });
  afterEach(cleanup);

  it("renders source, sink and a balanced 'Set aside' gate from analytics", async () => {
    mockAnalytics();
    const { container } = render(<MoneyFlow />);

    await waitFor(() => {
      expect(container.querySelector("svg")).toBeTruthy();
    });

    // Source + sink labels appear as SVG <text>.
    expect(container.textContent).toContain("Salary");
    expect(container.textContent).toContain("Rent");
    // Surplus = 6500 income − 3300 spend = 3200 set aside.
    expect(container.textContent).toContain("Set aside");

    // Ribbons exist: sources→hub (2) + hub→sinks (3 spend + 1 saved) = 6 fills.
    const ribbons = container.querySelectorAll("path[fill^='hsl']");
    expect(ribbons.length).toBeGreaterThanOrEqual(6);
  });

  it("exposes an accessible table of the same figures", async () => {
    mockAnalytics();
    const { getByRole } = render(<MoneyFlow />);
    await waitFor(() => {
      const table = getByRole("table", { hidden: true });
      expect(within(table).getByText(/From Salary/)).toBeTruthy();
      expect(within(table).getByText(/To Rent/)).toBeTruthy();
    });
  });

  it("shows an empty state when nothing has moved", async () => {
    apiGet.mockResolvedValue({ data: { totals_by_category: {} } });
    const { findByText } = render(<MoneyFlow />);
    expect(await findByText(/No money has moved yet/)).toBeTruthy();
  });
});
