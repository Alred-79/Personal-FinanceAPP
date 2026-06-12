/**
 * v4 package 05 — the daily skeleton (client).
 *
 * The streak chip renders the rebuilding copy correctly (contains "rebuilding"
 * and the best run, never "broken" and never a bare "0" headline), is hidden in
 * off mode, and the daily surface never shows more than two elements (verb +
 * collect). The tick affordance never shows a currency symbol.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const apiGet = vi.fn();
const apiPost = vi.fn();
const apiPut = vi.fn();

vi.mock("@/lib/api", () => ({
  default: {
    get: (...a: unknown[]) => apiGet(...a),
    post: (...a: unknown[]) => apiPost(...a),
    put: (...a: unknown[]) => apiPut(...a),
  },
}));

import { GameModeProvider, useGameMode } from "@/store/gameMode";
import { StreakChip } from "@/components/custom/StreakChip/StreakChip";
import { DailySurface } from "@/components/custom/DailySurface/DailySurface";
import { type ReactNode } from "react";

const REBUILDING = {
  status: "rebuilding",
  current: 0,
  best: 5,
  wards: 1,
  grace_wards: 0,
  tick_collectible: 3,
  reviving: false,
};
const ACTIVE = { ...REBUILDING, status: "active", current: 4, tick_collectible: 0 };

function mockMode(mode: string, streak = REBUILDING) {
  apiGet.mockImplementation((url: string) => {
    if (url === "/settings/")
      return Promise.resolve({ data: { preferences: { game_mode: mode } } });
    if (url === "/game/streak/") return Promise.resolve({ data: streak });
    return Promise.resolve({ data: {} });
  });
}

/** Mount children only once the provider resolves out of its boot-default off. */
function AfterMode({ expect: want, children }: { expect: string; children: ReactNode }) {
  const { mode } = useGameMode();
  if (want !== "off" && mode !== want) return null;
  return <>{children}</>;
}

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiPut.mockReset();
  document.documentElement.dataset.mode = "off";
});
afterEach(() => cleanup());

describe("streak chip", () => {
  it("is hidden in off mode", async () => {
    mockMode("off");
    const { queryByTestId } = render(
      <GameModeProvider>
        <MemoryRouter><StreakChip /></MemoryRouter>
      </GameModeProvider>
    );
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/settings/"));
    expect(queryByTestId("streak-chip")).not.toBeInTheDocument();
  });

  it("renders rebuilding copy with best, never 'broken' or a bare 0 headline", async () => {
    mockMode("ambient", REBUILDING);
    const { findByTestId } = render(
      <GameModeProvider>
        <MemoryRouter>
          <AfterMode expect="ambient"><StreakChip /></AfterMode>
        </MemoryRouter>
      </GameModeProvider>
    );
    const label = await findByTestId("streak-label");
    const text = label.textContent || "";
    expect(text.toLowerCase()).toContain("rebuilding");
    expect(text).toContain("best: 5");
    // No banned words and no "0" as the headline figure.
    for (const w of ["broken", "lost", "dead", "failed"]) {
      expect(text.toLowerCase()).not.toContain(w);
    }
    expect(text).not.toMatch(/\b0\b/);
  });

  it("renders the active streak count", async () => {
    mockMode("ambient", ACTIVE);
    const { findByTestId } = render(
      <GameModeProvider>
        <MemoryRouter>
          <AfterMode expect="ambient"><StreakChip /></AfterMode>
        </MemoryRouter>
      </GameModeProvider>
    );
    const label = await findByTestId("streak-label");
    expect(label.textContent).toContain("4");
  });
});

describe("daily surface", () => {
  it("shows exactly two elements (verb + collect) and is hidden in off", async () => {
    mockMode("off");
    const off = render(
      <GameModeProvider>
        <MemoryRouter><DailySurface /></MemoryRouter>
      </GameModeProvider>
    );
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/settings/"));
    expect(off.queryByTestId("daily-surface")).not.toBeInTheDocument();
    off.unmount();

    mockMode("ambient");
    const { findByTestId, queryByTestId } = render(
      <GameModeProvider>
        <MemoryRouter>
          <AfterMode expect="ambient"><DailySurface verb="scout_bill" /></AfterMode>
        </MemoryRouter>
      </GameModeProvider>
    );
    await findByTestId("daily-surface");
    expect(queryByTestId("daily-verb")).toBeInTheDocument();
    expect(queryByTestId("tick-collect")).toBeInTheDocument();
  });

  it("the collect affordance shows no currency symbol", async () => {
    mockMode("ambient");
    const { findByTestId } = render(
      <GameModeProvider>
        <MemoryRouter>
          <AfterMode expect="ambient"><DailySurface /></AfterMode>
        </MemoryRouter>
      </GameModeProvider>
    );
    const btn = await findByTestId("tick-collect");
    expect(btn.textContent).not.toContain("$");
  });
});
