import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render,
  screen,
  cleanup,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

const TIMELINE = [
  { date: "2026-03-01", balance: 1000, change: 0, label: "" },
  { date: "2026-03-15", balance: 800, change: -200, label: "" },
  { date: "2026-03-31", balance: 1200, change: 400, label: "" },
];

const FORECAST = {
  horizon_start: "2026-03-01",
  horizon_end: "2026-03-31",
  starting_balance: 1000,
  ending_balance: 1200,
  lowest_balance: 800,
  lowest_date: "2026-03-15",
  total_projected_expenses: 200,
  will_go_negative: false,
  first_negative_date: null,
  paths_below_zero: 12,
  paths_total: 300,
  regime_shift: {
    date: "2026-03-12",
    delta_per_day: 10,
    delta_per_month: 300,
    direction: "up" as const,
  },
  trough_band: { low: 500, median: 750, high: 950 },
  events: [{ date: "2026-03-15", income: 1000, expenses: 200, net: 800, label: "Paycheck, Rent" }],
  timeline: TIMELINE,
};

const ACTIVE_RESULT = {
  horizon_start: "2026-03-01",
  horizon_end: "2026-03-31",
  baseline_timeline: TIMELINE,
  scenario_timeline: [
    { date: "2026-03-01", balance: 1000, change: 0, label: "" },
    { date: "2026-03-31", balance: 1700, change: 700, label: "" },
  ],
  baseline_events: [],
  scenario_events: [],
  applied_changes: [{ id: "discrete_flow:0", kind: "expense", detail: "Purchase on 2026-03-10" }],
  ignored_changes: [],
  baseline: { name: "Baseline", result: { ending_balance: 1200, safe_to_spend: 300 } },
  scenario: {
    name: "What-If",
    scenario_id: null,
    result: {
      ending_balance: 1700,
      safe_to_spend: 450,
      lowest_balance: 600,
      first_negative_date: null,
      paths_below_zero: 10,
      paths_total: 300,
      trough_band: { low: 600, median: 900, high: 1100 },
    },
    delta: { ending_balance: 500, safe_to_spend: 150, lowest_balance: -200 },
  },
};

const { state, fetchForecast, fetchScenarios } = vi.hoisted(() => {
  const fetchForecast = vi.fn();
  const fetchScenarios = vi.fn();
  return {
    fetchForecast,
    fetchScenarios,
    state: {
      forecast: null as unknown,
      forecastLoaded: true,
      forecastHorizon: 30,
      fetchForecast,
      scenarios: [{ id: 1, name: "Saved A", overlay: {} }],
      scenariosLoaded: true,
      fetchScenarios,
      activeScenarioResult: null as unknown,
      compareResult: null as unknown,
      compareScenarios: vi.fn(),
      runScenario: vi.fn(),
      createScenario: vi.fn(),
      updateScenario: vi.fn(),
      clearActiveScenarioResult: vi.fn(),
      forecastEvidenceEnabled: false,
      fetchGoals: vi.fn(),
      goals: [],
    },
  };
});

// The page calls both `useStore()` (destructured) and `useStore(sel)`.
vi.mock("@/store/store", () => ({
  useStore: (sel?: (s: typeof state) => unknown) => (sel ? sel(state) : state),
}));

// Native Select shim (Radix is intractable in jsdom).
vi.mock("@/components/ui/select", () => {
  const Ctx = React.createContext<{
    value?: string;
    onValueChange?: (v: string) => void;
  }>({});
  const Select = ({ value, onValueChange, children }: {
    value?: string;
    onValueChange?: (v: string) => void;
    children: React.ReactNode;
  }) => React.createElement(Ctx.Provider, { value: { value, onValueChange } }, children);
  const SelectTrigger = ({ children }: { children: React.ReactNode }) =>
    React.createElement("div", null, children);
  const SelectValue = ({ placeholder }: { placeholder?: string }) => {
    const { value } = React.useContext(Ctx);
    return React.createElement("span", null, value || placeholder);
  };
  const SelectContent = ({ children }: { children: React.ReactNode }) => {
    const { onValueChange } = React.useContext(Ctx);
    return React.createElement(
      "div",
      { role: "listbox" },
      React.Children.map(children, (child) => {
        const el = child as React.ReactElement<{ value: string; children: React.ReactNode }>;
        return el
          ? React.createElement(
              "button",
              { type: "button", role: "option", onClick: () => onValueChange?.(el.props.value) },
              el.props.children
            )
          : null;
      })
    );
  };
  const SelectItem = ({ children }: { value: string; children: React.ReactNode }) =>
    React.createElement(React.Fragment, null, children);
  return { Select, SelectTrigger, SelectValue, SelectContent, SelectItem };
});

vi.mock("@/pages/Forecast/ForecastEvidencePanel", () => ({
  default: () => <div>Forecast evidence audit surface</div>,
}));

import Forecast from "@/pages/Forecast/Forecast";

beforeEach(() => {
  fetchForecast.mockClear();
  fetchScenarios.mockClear();
  state.forecast = FORECAST;
  state.activeScenarioResult = null;
  state.forecastEvidenceEnabled = false;
});
afterEach(() => cleanup());

function renderAt(path = "/forecast") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Forecast />
    </MemoryRouter>
  );
}

describe("Forecast page", () => {
  it("fetches the forecast on mount and shows the projection", () => {
    const { container } = renderAt();
    expect(fetchForecast).toHaveBeenCalled();
    expect(screen.getByText("Daily central path")).toBeInTheDocument();
    // The three tabs are present.
    expect(screen.getByRole("tab", { name: "Current outlook" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Test a decision" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Compare saved" })).toBeInTheDocument();
    expect(screen.getByText("−$200.00")).toBeInTheDocument();
    expect(screen.getByText("Lower modeled bound $500.00")).toBeInTheDocument();
    expect(screen.getByText("Median simulated low $750.00")).toBeInTheDocument();
    expect(screen.getByText("Central daily path low $800.00")).toBeInTheDocument();
    expect(
      screen.getByText("12 of 300 modeled paths fell below $0 over 30 days.")
    ).toBeInTheDocument();
    expect(screen.getByText(/Recent spending pace changed/i)).toBeInTheDocument();
    expect(container.textContent ?? "").not.toMatch(/5th percentile|95th percentile/i);
    expect(state.clearActiveScenarioResult).toHaveBeenCalled();
    expect(container.textContent ?? "").not.toMatch(/confidence|chance|calibrated|probability/i);
  });

  it("plots the low-point band proportionally on a domain anchored by $0 and the starting balance", () => {
    renderAt();

    const graphic = screen.getByRole("img", {
      name: /modeled low-point bounds run from \$500\.00 to \$950\.00/i,
    });
    expect(graphic).toHaveAttribute("data-domain-min", "0");
    expect(graphic).toHaveAttribute("data-domain-max", "1000");
    expect(graphic).toHaveAttribute("data-zero-position", "0");

    const band = screen.getByTestId("modeled-low-band");
    expect(Number(band.getAttribute("data-start-position"))).toBeCloseTo(50);
    expect(Number(band.getAttribute("data-width"))).toBeCloseTo(45);
    expect(Number(band.getAttribute("data-width"))).toBeLessThan(100);
    expect(screen.getByTestId("median-simulated-marker")).toBeInTheDocument();
    expect(screen.getByTestId("central-path-marker")).toBeInTheDocument();
  });

  it("extends the domain when the central path falls below the simulated lower bound", () => {
    state.forecast = {
      ...FORECAST,
      lowest_balance: -250,
      will_go_negative: true,
      first_negative_date: "2026-03-20",
      trough_band: { low: 500, median: 750, high: 950 },
    };
    renderAt();

    const graphic = screen.getByRole("img", {
      name: /central daily path reaches a low of -\$250\.00/i,
    });
    expect(graphic).toHaveAttribute("data-domain-min", "-250");
    expect(graphic).toHaveAttribute("data-domain-max", "1000");
    expect(screen.getByTestId("central-path-marker")).toHaveAttribute(
      "data-position",
      "0"
    );
  });

  it("extends the domain when the central path sits above the simulated upper bound", () => {
    state.forecast = {
      ...FORECAST,
      starting_balance: 50,
      lowest_balance: 500,
      ending_balance: 700,
      trough_band: { low: -100, median: 0, high: 100 },
    };
    renderAt();

    const graphic = screen.getByRole("img", {
      name: /central daily path reaches a low of \$500\.00/i,
    });
    expect(graphic).toHaveAttribute("data-domain-min", "-100");
    expect(graphic).toHaveAttribute("data-domain-max", "500");
    expect(screen.getByTestId("central-path-marker")).toHaveAttribute(
      "data-position",
      "100"
    );
  });

  it("keeps $0 visible and positions a mixed negative/positive band on the same scale", () => {
    state.forecast = {
      ...FORECAST,
      lowest_balance: -75,
      will_go_negative: true,
      first_negative_date: "2026-03-18",
      paths_below_zero: 120,
      trough_band: { low: -200, median: -50, high: 100 },
    };
    renderAt();

    const graphic = screen.getByRole("img", {
      name: /bounds run from -\$200\.00 to \$100\.00/i,
    });
    expect(graphic).toHaveAttribute("data-domain-min", "-200");
    expect(graphic).toHaveAttribute("data-domain-max", "1000");
    expect(Number(graphic.getAttribute("data-zero-position"))).toBeCloseTo(
      100 / 6
    );
    const band = screen.getByTestId("modeled-low-band");
    expect(Number(band.getAttribute("data-start-position"))).toBeCloseTo(0);
    expect(Number(band.getAttribute("data-width"))).toBeCloseTo(25);
    expect(screen.getByText("Central daily path low -$75.00")).toBeInTheDocument();
  });

  it("handles an all-negative band with $0 at the right edge", () => {
    state.forecast = {
      ...FORECAST,
      starting_balance: -50,
      lowest_balance: -350,
      ending_balance: -100,
      will_go_negative: true,
      first_negative_date: "2026-03-01",
      paths_below_zero: 300,
      trough_band: { low: -500, median: -300, high: -100 },
    };
    renderAt();

    const graphic = screen.getByRole("img", {
      name: /bounds run from -\$500\.00 to -\$100\.00/i,
    });
    expect(graphic).toHaveAttribute("data-domain-min", "-500");
    expect(graphic).toHaveAttribute("data-domain-max", "0");
    expect(graphic).toHaveAttribute("data-zero-position", "100");
    expect(Number(screen.getByTestId("modeled-low-band").getAttribute("data-width"))).toBeCloseTo(80);
  });

  it("describes coincident bounds and median without claiming every path shares one low", () => {
    state.forecast = {
      ...FORECAST,
      trough_band: { low: 500, median: 500, high: 500 },
    };
    renderAt();

    expect(screen.getByTestId("modeled-low-point")).toBeInTheDocument();
    expect(screen.queryByTestId("modeled-low-band")).not.toBeInTheDocument();
    expect(
      screen.getByText("Reported bounds and median coincide at $500.00")
    ).toBeInTheDocument();
    expect(screen.queryByText("Median simulated low $500.00")).not.toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: /reported bounds and median coincide at \$500\.00/i,
      })
    ).toBeInTheDocument();
    expect(screen.queryByText(/paths share one low/i)).not.toBeInTheDocument();
  });

  it("centers an all-zero degenerate domain instead of pinning it to an edge", () => {
    state.forecast = {
      ...FORECAST,
      starting_balance: 0,
      lowest_balance: 0,
      ending_balance: 0,
      trough_band: { low: 0, median: 0, high: 0 },
    };
    renderAt();

    const graphic = screen.getByRole("img", {
      name: /reported bounds and median coincide at \$0\.00/i,
    });
    expect(graphic).toHaveAttribute("data-domain-min", "0");
    expect(graphic).toHaveAttribute("data-domain-max", "0");
    expect(graphic).toHaveAttribute("data-zero-position", "50");
    expect(screen.getByTestId("modeled-low-point")).toHaveAttribute(
      "data-position",
      "50"
    );
  });

  it("combines median and upper-bound marks when they would overlap", () => {
    state.forecast = {
      ...FORECAST,
      trough_band: { low: 500, median: 950, high: 950 },
    };
    renderAt();

    expect(screen.getByTestId("median-high-marker")).toBeInTheDocument();
    expect(screen.queryByTestId("median-simulated-marker")).not.toBeInTheDocument();
    expect(
      screen.getByText("Median simulated / upper bound $950.00")
    ).toBeInTheDocument();
  });

  it("combines lower-bound and median marks when they would overlap", () => {
    state.forecast = {
      ...FORECAST,
      trough_band: { low: 500, median: 500, high: 950 },
    };
    renderAt();

    expect(screen.getByTestId("median-low-marker")).toBeInTheDocument();
    expect(screen.queryByTestId("median-simulated-marker")).not.toBeInTheDocument();
    expect(
      screen.getByText("Lower bound / median simulated $500.00")
    ).toBeInTheDocument();
    expect(screen.getByText("Upper modeled bound $950.00")).toBeInTheDocument();
  });

  it("restores the optional forecast-evidence surface behind progressive disclosure", () => {
    state.forecastEvidenceEnabled = true;
    renderAt();
    expect(screen.getByText("Advanced: forecast evidence")).toBeInTheDocument();
    expect(screen.getByText("Forecast evidence audit surface")).toBeInTheDocument();
  });

  it("renders the baseline-vs-scenario overlay (two series) when a run exists", () => {
    state.activeScenarioResult = ACTIVE_RESULT;
    // ?goal deep-links straight to the What-If tab (avoids Radix pointer quirks
    // in jsdom), where the overlay card renders.
    renderAt("/forecast?goal=1");
    expect(screen.getByText("Decision answer")).toBeInTheDocument();
    expect(screen.getAllByText(/10 of 300/)).toHaveLength(2);
    expect(screen.getByText("Change vs current")).toBeInTheDocument();
    expect(screen.getAllByText(/200\.00/).length).toBeGreaterThan(0);
  });

  it("does not mislabel a horizon-start scenario cashflow as its starting balance", () => {
    state.activeScenarioResult = {
      ...ACTIVE_RESULT,
      scenario_timeline: [
        // The first point can already include a flow on horizon_start, so its
        // balance is deliberately different from the true pre-flow balance.
        { date: "2026-03-01", balance: 1400, change: 400, label: "Income on start" },
        { date: "2026-03-31", balance: 1700, change: 300, label: "" },
      ],
    };
    renderAt("/forecast?goal=1");

    const graphic = screen.getByRole("img", {
      name: /10 of 300 modeled paths fell below \$0/i,
    });
    expect(graphic).not.toHaveAccessibleName(/starting balance/i);
    expect(screen.queryByTestId("starting-balance-marker")).not.toBeInTheDocument();
    expect(screen.queryByText(/^Starting balance /)).not.toBeInTheDocument();
  });

  it("has a real commit affordance (replacing the dead banner) once a scenario is picked", async () => {
    renderAt("/forecast?scenario=1");
    // Deep link defaults to the What-If tab; the picker is pre-seeded to id 1.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Commit this plan/i })).toBeInTheDocument()
    );
  });
});
