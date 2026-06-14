import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";

const { compareScenarios, state } = vi.hoisted(() => {
  const compareScenarios = vi.fn().mockResolvedValue(undefined);
  return {
    compareScenarios,
    state: {
      compareResult: {
        columns: [
          {
            name: "Baseline",
            result: {
              ending_balance: 1000,
              lowest_balance: 200,
              safe_to_spend: 300,
              overdraft_probability: 0.1,
              runway_days: 90,
              goal_reach: {},
            },
          },
          {
            name: "Aggressive",
            result: {
              ending_balance: 1500,
              lowest_balance: 400,
              safe_to_spend: 450,
              overdraft_probability: 0.6,
              runway_days: 60,
              goal_reach: {},
            },
          },
        ],
      },
      compareScenarios,
    },
  };
});

vi.mock("@/store/store", () => ({
  useStore: (sel?: (s: typeof state) => unknown) => (sel ? sel(state) : state),
}));

import ScenarioCompare from "@/components/custom/ScenarioCompare/ScenarioCompare";

beforeEach(() => compareScenarios.mockClear());
afterEach(() => cleanup());

describe("ScenarioCompare", () => {
  it("prompts when no scenarios are selected", () => {
    render(<ScenarioCompare scenarioIds={[]} />);
    expect(screen.getByText(/Pick two or more/i)).toBeInTheDocument();
    expect(compareScenarios).not.toHaveBeenCalled();
  });

  it("fires the compare thunk and renders N+1 columns + metric rows", async () => {
    render(<ScenarioCompare scenarioIds={[1, 2]} horizonDays={60} />);
    await waitFor(() =>
      expect(compareScenarios).toHaveBeenCalledWith([1, 2], 60)
    );
    // Column headers (baseline + scenario).
    expect(screen.getAllByText("Baseline").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Aggressive").length).toBeGreaterThan(0);
    // A comparison metric row renders both columns' ending balances (also
    // echoed in the per-column figure plates, so there are 2 of each).
    expect(screen.getAllByText("$1,000.00").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$1,500.00").length).toBeGreaterThan(0);
    // Overdraft risk rendered as a percentage.
    expect(screen.getByText("60%")).toBeInTheDocument();
  });
});
