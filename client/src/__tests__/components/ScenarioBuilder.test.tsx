import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  cleanup,
  waitFor,
  act,
} from "@testing-library/react";
import React from "react";

// Store mock supporting selector-style useStore((s) => s.x).
const { runScenario, createScenario, updateScenario, state } = vi.hoisted(() => {
  const runScenario = vi.fn().mockResolvedValue(undefined);
  const createScenario = vi.fn().mockResolvedValue({ id: 99 });
  const updateScenario = vi.fn().mockResolvedValue(undefined);
  return {
    runScenario,
    createScenario,
    updateScenario,
    state: {
      goals: [{ id: 3, name: "Emergency Fund" }],
      runScenario,
      createScenario,
      updateScenario,
    },
  };
});
vi.mock("@/store/store", () => ({
  useStore: (sel?: (s: typeof state) => unknown) => (sel ? sel(state) : state),
}));

// Deterministic native Select shim (Radix is intractable in jsdom).
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
              {
                type: "button",
                role: "option",
                onClick: () => onValueChange?.(el.props.value),
              },
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

import ScenarioBuilder from "@/components/custom/ScenarioBuilder/ScenarioBuilder";

beforeEach(() => {
  vi.useFakeTimers();
  runScenario.mockClear();
  createScenario.mockClear();
  updateScenario.mockClear();
});
afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe("ScenarioBuilder", () => {
  it("renders the kind buttons and an empty state", () => {
    render(<ScenarioBuilder />);
    expect(screen.getByText(/Stack a change/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Recurring income/i })).toBeInTheDocument();
  });

  it("adds a row and debounce-runs the live evaluate", async () => {
    render(<ScenarioBuilder />);
    fireEvent.click(screen.getByRole("button", { name: /Recurring income/i }));
    expect(screen.getAllByTestId("scenario-row")).toHaveLength(1);

    // The debounced run fires only after the timer elapses.
    expect(runScenario).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(450);
    });
    expect(runScenario).toHaveBeenCalledTimes(1);
    const [overlay] = runScenario.mock.calls[0];
    expect(overlay.added_recurring).toHaveLength(1);
    expect(overlay.added_recurring[0].kind).toBe("income");
  });

  it("Save creates a scenario with the built overlay", async () => {
    vi.useRealTimers(); // the save path awaits a real promise
    render(<ScenarioBuilder />);
    fireEvent.click(screen.getByRole("button", { name: /Recurring expense/i }));
    fireEvent.change(screen.getByLabelText("Scenario name"), {
      target: { value: "Belt tightening" },
    });
    fireEvent.change(screen.getByLabelText("Amount"), {
      target: { value: "120" },
    });

    fireEvent.click(screen.getByRole("button", { name: /Save scenario/i }));
    await waitFor(() => expect(createScenario).toHaveBeenCalledTimes(1));
    const [name, overlay] = createScenario.mock.calls[0];
    expect(name).toBe("Belt tightening");
    expect(overlay.added_recurring[0].amount).toBe(120);
    expect(overlay.added_recurring[0].kind).toBe("expense");
  });

  it("removing a row clears it from the list", () => {
    render(<ScenarioBuilder />);
    fireEvent.click(screen.getByRole("button", { name: /One-off flow/i }));
    expect(screen.getAllByTestId("scenario-row")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: /Remove row/i }));
    expect(screen.queryAllByTestId("scenario-row")).toHaveLength(0);
  });
});
