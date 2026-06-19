import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { createElement, type ReactNode } from "react";

// useAssistantChat imports refreshOnce from @/lib/api — stub it so the module
// graph (axios) doesn't need to fully initialize.
vi.mock("@/lib/api", () => ({
  default: { post: vi.fn() },
  refreshOnce: vi.fn().mockResolvedValue(undefined),
}));

import { useAssistantChat } from "@/hooks/useAssistantChat";

const wrapper = ({ children }: { children: ReactNode }) =>
  createElement(MemoryRouter, null, children);

describe("useAssistantChat — F3 SSE abort on unmount", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("aborts the in-flight stream fetch when the hook unmounts", async () => {
    let capturedSignal: AbortSignal | undefined;
    // A reader that blocks forever (never resolves) until aborted — so the stream
    // is genuinely in-flight at unmount.
    const neverEndingReader = {
      read: () => new Promise(() => {}),
    };
    const fetchMock = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      capturedSignal = init.signal ?? undefined;
      return Promise.resolve({
        ok: true,
        status: 200,
        body: { getReader: () => neverEndingReader },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result, unmount } = renderHook(() => useAssistantChat(), { wrapper });

    // Kick off a send (fire-and-forget; the stream never completes).
    act(() => {
      void result.current.send("hello there");
    });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(capturedSignal).toBeDefined();
    expect(capturedSignal!.aborted).toBe(false);

    // Unmounting must abort the in-flight fetch (F3).
    unmount();
    expect(capturedSignal!.aborted).toBe(true);
  });
});
