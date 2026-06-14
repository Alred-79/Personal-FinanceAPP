import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
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
  timeline: TIMELINE,
};

const ACTIVE_RESULT = {
  baseline: { name: "Baseline", result: { ending_balance: 1200, safe_to_spend: 300 } },
  scenario: {
    name: "What-If",
    scenario_id: null,
    result: {
      ending_balance: 1700,
      safe_to_spend: 450,
      overdraft_probability: 0.1,
      trough_band: { low: 600, median: 900, high: 1100 },
      timeline: [
        { date: "2026-03-01", balance: 1000, change: 0, label: "" },
        { date: "2026-03-31", balance: 1700, change: 700, label: "" },
      ],
    },
    delta: { ending_balance: 500, safe_to_spend: 150 },
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
      React.Children.map(children, (child: React.ReactElement) =>
        child
          ? React.createElement(
              "button",
              { type: "button", role: "option", onClick: () => onValueChange?.(child.props.value) },
              child.props.children
            )
          : null
      )
    );
  };
  const SelectItem = ({ children }: { value: string; children: React.ReactNode }) =>
    React.createElement(React.Fragment, null, children);
  return { Select, SelectTrigger, SelectValue, SelectContent, SelectItem };
});

import Forecast from "@/pages/Forecast/Forecast";

beforeEach(() => {
  fetchForecast.mockClear();
  fetchScenarios.mockClear();
  state.forecast = FORECAST;
  state.activeScenarioResult = null;
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
    renderAt();
    expect(fetchForecast).toHaveBeenCalled();
    expect(screen.getByText("Running Balance")).toBeInTheDocument();
    // The three tabs are present.
    expect(screen.getByRole("tab", { name: "Projection" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "What-If" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Compare" })).toBeInTheDocument();
  });

  it("renders the baseline-vs-scenario overlay (two series) when a run exists", () => {
    state.activeScenarioResult = ACTIVE_RESULT;
    // ?goal deep-links straight to the What-If tab (avoids Radix pointer quirks
    // in jsdom), where the overlay card renders.
    renderAt("/forecast?goal=1");
    // The overlay card titles the two series and stamps the overdraft prob.
    expect(screen.getByText("Baseline vs What-If")).toBeInTheDocument();
    expect(screen.getByText(/Overdraft 10%/)).toBeInTheDocument();
    // Both delta figures rendered (a credit gain).
    expect(screen.getByText("Δ ending")).toBeInTheDocument();
    expect(screen.getByText("$500.00")).toBeInTheDocument();
  });

  it("has a real commit affordance (replacing the dead banner) once a scenario is picked", async () => {
    renderAt("/forecast?scenario=1");
    // Deep link defaults to the What-If tab; the picker is pre-seeded to id 1.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Commit this plan/i })).toBeInTheDocument()
    );
  });
});
