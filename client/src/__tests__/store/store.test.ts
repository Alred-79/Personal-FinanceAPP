import { describe, it, expect, afterEach, vi } from "vitest";
import { act } from "@testing-library/react";

// Avoid real network from logout()'s fire-and-forget api.post and the toast
// helpers the store imports.
vi.mock("@/lib/api", () => ({
  default: {
    post: vi.fn().mockResolvedValue({ data: {} }),
    get: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}));

import { useStore } from "@/store/store";
import { resetGameMode } from "@/store/gameMode";

afterEach(() => {
  // Reset selectedAccountId between tests
  act(() => {
    useStore.getState().setSelectedAccountId("all");
  });
});

describe("Store defaults", () => {
  it("selectedAccountId defaults to 'all'", () => {
    expect(useStore.getState().selectedAccountId).toBe("all");
  });

  it("isLoggedIn defaults to false", () => {
    expect(useStore.getState().isLoggedIn).toBe(false);
  });

  it("isLoading defaults to false", () => {
    expect(useStore.getState().isLoading).toBe(false);
  });

  it("transactions defaults to empty array", () => {
    expect(useStore.getState().transactions).toEqual([]);
  });

  it("budgets defaults to empty array", () => {
    expect(useStore.getState().budgets).toEqual([]);
  });

  it("netWorth defaults to empty array", () => {
    expect(useStore.getState().netWorth).toEqual([]);
  });

  it("goals defaults to empty array", () => {
    expect(useStore.getState().goals).toEqual([]);
  });

  it("recentTransactions defaults to empty array", () => {
    expect(useStore.getState().recentTransactions).toEqual([]);
  });

  it("notifications defaults to empty array", () => {
    expect(useStore.getState().notifications).toEqual([]);
  });

  it("subscriptions defaults to empty array", () => {
    expect(useStore.getState().subscriptions).toEqual([]);
  });

  it("user defaults to null", () => {
    expect(useStore.getState().user).toBeNull();
  });
});

describe("setSelectedAccountId", () => {
  it("updates selectedAccountId to a given string", () => {
    act(() => {
      useStore.getState().setSelectedAccountId("123");
    });
    expect(useStore.getState().selectedAccountId).toBe("123");
  });

  it("can be reset back to 'all'", () => {
    act(() => {
      useStore.getState().setSelectedAccountId("42");
    });
    act(() => {
      useStore.getState().setSelectedAccountId("all");
    });
    expect(useStore.getState().selectedAccountId).toBe("all");
  });
});

describe("logout resets financial + game state", () => {
  it("clears Safe-to-Spend, budget, selected account, and s2sPrefs to initial", () => {
    // Dirty the financial slices the old logout forgot.
    act(() => {
      useStore.setState({
        safeToSpend: {
          available: 500,
          horizon_end: "2026-06-30",
          horizon_source: "month",
          days_remaining: 17,
          daily_plan: 29,
          breakdown: {
            current_balance: 1000,
            upcoming_bills: 200,
            projected_income: 0,
            goal_earmarks: 0,
            goal_contributions: 0,
            buffer: 0,
          },
          config: {
            horizon: "month",
            include_income: true,
            include_goals: true,
            buffer: 0,
          },
        },
        budgetAllotment: 42,
        selectedAccountId: "7",
        s2sPrefs: {
          s2s_horizon: "week",
          s2s_include_income: false,
          s2s_include_goals: false,
          s2s_buffer: 100,
        },
        isLoggedIn: true,
        user: { id: 1, username: "x", full_name: null },
      });
    });

    act(() => {
      useStore.getState().logout();
    });

    const s = useStore.getState();
    expect(s.safeToSpend).toBeNull();
    expect(s.budgetAllotment).toBe(1);
    expect(s.selectedAccountId).toBe("all");
    expect(s.s2sPrefs).toEqual({
      s2s_horizon: "paycheck",
      s2s_include_income: true,
      s2s_include_goals: true,
      s2s_buffer: 0,
    });
    expect(s.isLoggedIn).toBe(false);
    expect(s.user).toBeNull();
  });

  it("clears every data slice (no leftover transactions/goals/etc.)", () => {
    act(() => {
      useStore.setState({
        transactions: [{ id: 1 } as never],
        recentTransactions: [{ id: 2 } as never],
        goals: [{ name: "g" } as never],
        budgets: [{ id: 3 } as never],
        accounts: [{ id: 4 } as never],
        notifications: [{ id: 5 } as never],
        unreadCount: 9,
        forecast: { horizon_start: "x" } as never,
        linkToken: "tok",
      });
    });

    act(() => {
      useStore.getState().logout();
    });

    const s = useStore.getState();
    expect(s.transactions).toEqual([]);
    expect(s.recentTransactions).toEqual([]);
    expect(s.goals).toEqual([]);
    expect(s.budgets).toEqual([]);
    expect(s.accounts).toEqual([]);
    expect(s.notifications).toEqual([]);
    expect(s.unreadCount).toBe(0);
    expect(s.forecast).toBeNull();
    expect(s.linkToken).toBeNull();
  });

  it("resets a mounted game-mode provider back to off on logout", async () => {
    // Mount a real GameModeProvider so it registers its reset hook, switch it to
    // a game mode, then assert logout() drives it back to off — game chrome must
    // not survive a sign-out.
    const { render, screen, act: rtlAct, cleanup } = await import(
      "@testing-library/react"
    );
    const { GameModeProvider, useGameMode } = await import("@/store/gameMode");
    const { createElement } = await import("react");

    let setMode!: (m: "off" | "ambient" | "full") => void;
    function Probe() {
      const gm = useGameMode();
      setMode = gm.setMode;
      return createElement("div", { "data-testid": "mode" }, gm.mode);
    }

    render(
      createElement(GameModeProvider, null, createElement(Probe))
    );

    rtlAct(() => setMode("full"));
    expect(screen.getByTestId("mode").textContent).toBe("full");

    rtlAct(() => {
      useStore.getState().logout();
    });
    expect(screen.getByTestId("mode").textContent).toBe("off");
    cleanup();
  });

  it("exposes a callable resetGameMode bridge", () => {
    expect(typeof resetGameMode).toBe("function");
    expect(() => resetGameMode()).not.toThrow();
  });
});
