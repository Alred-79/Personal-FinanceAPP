import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act } from "@testing-library/react";

// Controllable api mock so we can assert paths, payloads, and abort behaviour.
const { apiGet, apiPost, apiPut, apiDelete } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  default: { get: apiGet, post: apiPost, put: apiPut, delete: apiDelete },
}));
vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast: vi.fn() }),
  toast: vi.fn(),
}));

import { useStore } from "@/store/store";

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiPut.mockReset();
  apiDelete.mockReset();
  apiGet.mockResolvedValue({ data: [] });
  apiPost.mockResolvedValue({ data: {} });
  apiPut.mockResolvedValue({ data: {} });
  apiDelete.mockResolvedValue({ data: {} });
  act(() => {
    useStore.setState({
      scenarios: [],
      scenariosLoaded: false,
      activeScenarioResult: null,
      compareResult: null,
      committedPlan: null,
    });
  });
});
afterEach(() => vi.restoreAllMocks());

describe("scenario store defaults + logout reset", () => {
  it("defaults are empty/null", () => {
    const s = useStore.getState();
    expect(s.scenarios).toEqual([]);
    expect(s.scenariosLoaded).toBe(false);
    expect(s.activeScenarioResult).toBeNull();
    expect(s.compareResult).toBeNull();
    expect(s.committedPlan).toBeNull();
  });

  it("logout() resets every scenario slice", () => {
    act(() => {
      useStore.setState({
        scenarios: [{ id: 1, name: "x" } as never],
        scenariosLoaded: true,
        activeScenarioResult: { baseline: {} } as never,
        compareResult: { columns: [] } as never,
        committedPlan: { plan_id: 9, rule_ids: [1] },
      });
    });
    act(() => useStore.getState().logout());
    const s = useStore.getState();
    expect(s.scenarios).toEqual([]);
    expect(s.scenariosLoaded).toBe(false);
    expect(s.activeScenarioResult).toBeNull();
    expect(s.compareResult).toBeNull();
    expect(s.committedPlan).toBeNull();
  });
});

describe("scenario CRUD (refetch after mutation)", () => {
  it("fetchScenarios loads from GET /scenarios/", async () => {
    apiGet.mockResolvedValueOnce({ data: [{ id: 1, name: "Plan", overlay: {} }] });
    await act(async () => {
      await useStore.getState().fetchScenarios();
    });
    expect(apiGet).toHaveBeenCalledWith("/scenarios/");
    expect(useStore.getState().scenarios).toHaveLength(1);
    expect(useStore.getState().scenariosLoaded).toBe(true);
  });

  it("createScenario POSTs then refetches", async () => {
    apiPost.mockResolvedValueOnce({ data: { id: 3, name: "New", overlay: {} } });
    apiGet.mockResolvedValueOnce({ data: [{ id: 3, name: "New", overlay: {} }] });
    let created;
    await act(async () => {
      created = await useStore.getState().createScenario("New", {
        added_recurring: [],
        excluded_source_ids: [],
        overridden_recurring: [],
        discrete_flows: [],
        goal_mutations: [],
        config_overrides: {},
      });
    });
    expect(apiPost).toHaveBeenCalledWith(
      "/scenarios/",
      expect.objectContaining({ name: "New" })
    );
    expect(apiGet).toHaveBeenCalledWith("/scenarios/"); // refetch
    expect((created as { id: number }).id).toBe(3);
  });

  it("updateScenario PUTs to the id path then refetches", async () => {
    await act(async () => {
      await useStore.getState().updateScenario(5, "Renamed", {
        added_recurring: [],
        excluded_source_ids: [],
        overridden_recurring: [],
        discrete_flows: [],
        goal_mutations: [],
        config_overrides: {},
      });
    });
    expect(apiPut).toHaveBeenCalledWith(
      "/scenarios/5/",
      expect.objectContaining({ name: "Renamed" })
    );
    expect(apiGet).toHaveBeenCalledWith("/scenarios/");
  });

  it("deleteScenario DELETEs then refetches", async () => {
    await act(async () => {
      await useStore.getState().deleteScenario(7);
    });
    expect(apiDelete).toHaveBeenCalledWith("/scenarios/7/");
    expect(apiGet).toHaveBeenCalledWith("/scenarios/");
  });

  it("createScenario throws on write failure", async () => {
    apiPost.mockRejectedValueOnce(new Error("boom"));
    await expect(
      act(async () => {
        await useStore.getState().createScenario("X", {
          added_recurring: [],
          excluded_source_ids: [],
          overridden_recurring: [],
          discrete_flows: [],
          goal_mutations: [],
          config_overrides: {},
        });
      })
    ).rejects.toThrow();
  });
});

describe("runScenario (live evaluate, abortable)", () => {
  const EMPTY = {
    added_recurring: [],
    excluded_source_ids: [],
    overridden_recurring: [],
    discrete_flows: [],
    goal_mutations: [],
    config_overrides: {},
  };

  it("POSTs the overlay to /scenarios/evaluate/ and stores the diff", async () => {
    apiPost.mockResolvedValueOnce({
      data: { baseline: { result: {} }, scenario: { result: {}, delta: {} } },
    });
    await act(async () => {
      await useStore.getState().runScenario(EMPTY, { name: "Live", horizonDays: 60 });
    });
    expect(apiPost).toHaveBeenCalledWith(
      "/scenarios/evaluate/",
      expect.objectContaining({ name: "Live", horizon_days: 60, overlay: EMPTY }),
      expect.objectContaining({ signal: expect.anything() })
    );
    expect(useStore.getState().activeScenarioResult).not.toBeNull();
  });

  it("a stale (aborted) run does not overwrite a fresher result", async () => {
    // First call hangs; second resolves. The first must be aborted and ignored.
    let resolveFirst: (v: unknown) => void = () => {};
    apiPost
      .mockImplementationOnce(
        (_url, _body, cfg) =>
          new Promise((resolve, reject) => {
            resolveFirst = resolve;
            (cfg.signal as AbortSignal).addEventListener("abort", () => {
              const e = new Error("canceled") as Error & { name: string };
              e.name = "CanceledError";
              reject(e);
            });
          })
      )
      .mockResolvedValueOnce({ data: { scenario: { result: { tag: "fresh" } } } });

    let p1: Promise<void>;
    await act(async () => {
      p1 = useStore.getState().runScenario(EMPTY);
      // Kick off a second run that supersedes the first.
      await useStore.getState().runScenario(EMPTY);
      // Now let the first (already aborted) call settle.
      resolveFirst({ data: { scenario: { result: { tag: "stale" } } } });
      await p1;
    });

    const r = useStore.getState().activeScenarioResult as unknown as {
      scenario: { result: { tag: string } };
    };
    expect(r.scenario.result.tag).toBe("fresh");
  });
});

describe("compareScenarios + commitScenario", () => {
  it("compareScenarios POSTs ids and stores the columns", async () => {
    apiPost.mockResolvedValueOnce({ data: { columns: [{ name: "Baseline" }] } });
    await act(async () => {
      await useStore.getState().compareScenarios([1, 2], 120);
    });
    expect(apiPost).toHaveBeenCalledWith("/scenarios/compare/", {
      scenario_ids: [1, 2],
      horizon_days: 120,
    });
    expect(useStore.getState().compareResult).not.toBeNull();
  });

  it("commitScenario runs propose→confirm and refetches forecast + goals", async () => {
    apiPost
      .mockResolvedValueOnce({ data: { token: "tok-123" } }) // propose
      .mockResolvedValueOnce({
        data: { result: { plan_id: 42, rule_ids: [7] } },
      }); // confirm
    apiGet.mockResolvedValue({ data: [] }); // forecast + goals refetch

    let result;
    await act(async () => {
      result = await useStore.getState().commitScenario(9, "My plan");
    });

    expect(apiPost).toHaveBeenNthCalledWith(1, "/assistant/actions/propose/", {
      action: "scenario_commit",
      params: { scenario_id: 9, name: "My plan" },
    });
    expect(apiPost).toHaveBeenNthCalledWith(2, "/assistant/actions/confirm/", {
      token: "tok-123",
    });
    expect((result as { plan_id: number }).plan_id).toBe(42);
    expect(useStore.getState().committedPlan).toEqual({ plan_id: 42, rule_ids: [7] });
    // Refetch fired for both forecast and goals.
    expect(apiGet).toHaveBeenCalledWith("/forecast", expect.anything());
    expect(apiGet).toHaveBeenCalledWith("/goals");
  });
});
