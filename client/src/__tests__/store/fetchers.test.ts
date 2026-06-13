import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act } from "@testing-library/react";

// Controllable api mock: each get() resolves only when we tell it to, so we can
// force a stale (earlier) response to land AFTER a fresh one.
const apiGet = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({
  default: {
    get: apiGet,
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}));
vi.mock("@/hooks/useToast", () => ({
  useToast: () => ({ toast: vi.fn() }),
  toast: vi.fn(),
}));

import { useStore } from "@/store/store";

beforeEach(() => {
  apiGet.mockReset();
  act(() => {
    useStore.setState({ transactions: [], transactionTotal: 0 });
  });
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("fetchAccountTransactions AbortController", () => {
  it("aborts the in-flight request when a newer search fires", async () => {
    const signals: AbortSignal[] = [];
    // Capture the AbortSignal each call receives; never resolve, so we can
    // observe the abort on the first when the second supersedes it.
    apiGet.mockImplementation((_url: string, config: { signal: AbortSignal }) => {
      signals.push(config.signal);
      return new Promise(() => {});
    });

    act(() => {
      void useStore.getState().fetchAccountTransactions("all", { q: "coff" });
    });
    act(() => {
      void useStore.getState().fetchAccountTransactions("all", { q: "coffee" });
    });

    expect(signals).toHaveLength(2);
    // The first request's signal is aborted by the second call.
    expect(signals[0].aborted).toBe(true);
    expect(signals[1].aborted).toBe(false);
  });

  it("a slow stale response does not overwrite the fresh one", async () => {
    // First call: resolves LATE with stale data. Second call: resolves FIRST
    // with fresh data. The store must end up showing the fresh result.
    let resolveStale!: (v: unknown) => void;
    let resolveFresh!: (v: unknown) => void;

    apiGet
      .mockImplementationOnce(
        (_url: string, config: { signal: AbortSignal }) =>
          new Promise((resolve, reject) => {
            // Reject as a cancellation when aborted (matches axios behavior).
            config.signal.addEventListener("abort", () => {
              const err = new Error("canceled");
              (err as { name: string }).name = "CanceledError";
              reject(err);
            });
            resolveStale = resolve;
          })
      )
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFresh = resolve;
          })
      );

    let p1!: Promise<void>;
    let p2!: Promise<void>;
    act(() => {
      p1 = useStore.getState().fetchAccountTransactions("all", { q: "stale" });
    });
    act(() => {
      p2 = useStore.getState().fetchAccountTransactions("all", { q: "fresh" });
    });

    // Fresh resolves first and writes its result.
    await act(async () => {
      resolveFresh({
        data: { items: [{ id: 2, category: "Food", title: "fresh" }], total: 1 },
      });
      await p2;
    });
    expect(useStore.getState().transactions.map((t) => t.id)).toEqual([2]);

    // Now the stale call "resolves" late — but it was aborted, so its handler
    // is the rejection path and it must NOT overwrite the fresh result.
    await act(async () => {
      resolveStale({
        data: { items: [{ id: 1, category: "Food", title: "stale" }], total: 1 },
      });
      await p1.catch(() => {});
    });
    expect(useStore.getState().transactions.map((t) => t.id)).toEqual([2]);
  });
});

describe("fetchForecast AbortController", () => {
  it("aborts the previous horizon request when a newer one fires", () => {
    const signals: AbortSignal[] = [];
    apiGet.mockImplementation((_url: string, config: { signal: AbortSignal }) => {
      signals.push(config.signal);
      return new Promise(() => {});
    });

    act(() => {
      void useStore.getState().fetchForecast(30);
    });
    act(() => {
      void useStore.getState().fetchForecast(90);
    });

    expect(signals).toHaveLength(2);
    expect(signals[0].aborted).toBe(true);
    expect(signals[1].aborted).toBe(false);
  });
});
