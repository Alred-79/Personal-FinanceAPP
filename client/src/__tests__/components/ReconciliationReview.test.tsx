import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";

import type { ImportSession } from "@/types";

// The component reads patchImportRow / discardImportSession off the zustand store
// via selectors; mock useStore to return our spies for those selectors.
const { patchSpy, discardSpy } = vi.hoisted(() => ({
  patchSpy: vi.fn(),
  discardSpy: vi.fn(),
}));

vi.mock("@/store/store", () => ({
  useStore: (selector: (s: unknown) => unknown) =>
    selector({
      patchImportRow: patchSpy,
      discardImportSession: discardSpy,
    }),
}));

import ReconciliationReview from "@/components/custom/Reconciliation/ReconciliationReview";

function makeSession(title = "Coffee"): ImportSession {
  return {
    id: 1,
    account_id: 1,
    source_kind: "image",
    detected_kind: "statement",
    status: "pending_review",
    balance_check: { actual_delta: 0, reconciled: true, exception_count: 0 },
    rows: [
      {
        id: 10,
        title,
        amount: -4.5,
        date: "2026-03-01",
        category: "Food",
        status: "ok",
        included: true,
      },
    ],
  };
}

describe("ReconciliationReview — F2 keystroke race", () => {
  beforeEach(() => {
    patchSpy.mockReset();
    discardSpy.mockReset();
  });
  afterEach(() => cleanup());

  it("does NOT PATCH on each keystroke — only onBlur, and only once", async () => {
    patchSpy.mockResolvedValue(makeSession("Coffee Shop"));
    const onSessionChange = vi.fn();
    render(
      <ReconciliationReview
        session={makeSession()}
        onSessionChange={onSessionChange}
        onCommitted={vi.fn()}
        onDiscarded={vi.fn()}
      />
    );

    const titleInput = screen.getByDisplayValue("Coffee") as HTMLInputElement;
    // Three keystrokes — no PATCH should fire yet.
    fireEvent.change(titleInput, { target: { value: "Coffee S" } });
    fireEvent.change(titleInput, { target: { value: "Coffee Sh" } });
    fireEvent.change(titleInput, { target: { value: "Coffee Shop" } });
    expect(patchSpy).not.toHaveBeenCalled();

    // One settled PATCH on blur.
    fireEvent.blur(titleInput);
    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1));
    expect(patchSpy).toHaveBeenCalledWith(1, 10, { title: "Coffee Shop" });
  });

  it("ignores a slow earlier response so it can't overwrite a newer edit", async () => {
    // First PATCH resolves SLOWLY with a stale session; second resolves fast.
    let resolveSlow: (v: ImportSession) => void = () => {};
    const slow = new Promise<ImportSession>((res) => {
      resolveSlow = res;
    });
    const fastSession = makeSession("NEW");
    patchSpy
      .mockReturnValueOnce(slow) // first edit's PATCH (will resolve last)
      .mockResolvedValueOnce(fastSession); // second edit's PATCH (resolves first)

    const onSessionChange = vi.fn();
    render(
      <ReconciliationReview
        session={makeSession()}
        onSessionChange={onSessionChange}
        onCommitted={vi.fn()}
        onDiscarded={vi.fn()}
      />
    );
    const titleInput = screen.getByDisplayValue("Coffee") as HTMLInputElement;

    // First edit + blur (PATCH #1, hangs).
    fireEvent.change(titleInput, { target: { value: "OLD" } });
    fireEvent.blur(titleInput);
    // Second edit + blur (PATCH #2, resolves immediately with the newer session).
    fireEvent.change(titleInput, { target: { value: "NEW" } });
    fireEvent.blur(titleInput);

    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(2));
    // The fast (newer) response applied.
    await waitFor(() =>
      expect(onSessionChange).toHaveBeenCalledWith(fastSession)
    );

    // Now the slow (older) response arrives — it MUST be dropped (stale token).
    const staleSession = makeSession("OLD");
    resolveSlow(staleSession);
    await Promise.resolve();
    await Promise.resolve();
    expect(onSessionChange).not.toHaveBeenCalledWith(staleSession);
  });
});
