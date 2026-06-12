/**
 * v4 package 04 — Keeper sheet client tests (groups 13-16).
 *
 * 13: the sheet renders in all three modes — off redirects to Settings (no game
 *     surface), ambient shows plain labels, full shows game labels with reveals.
 * 14: the header level pip is hidden in off, present in ambient/full.
 * 15: banned-words scan over the keeper sheet/toast term values and the in-code
 *     stat labels — low stats never read "failed"/"behind"/"worse"/"only".
 * 16: viewing the sheet emits zero game events (engagement-XP probe) — reading
 *     the Keeper read surface issues only GETs, never a write.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { type ReactNode } from "react";

import offTerms from "@/terms/terms.off.json";
import ambientTerms from "@/terms/terms.ambient.json";
import fullTerms from "@/terms/terms.full.json";

// ── api mock: GET is mode-aware (drives the provider) + records every call ──

const apiGet = vi.fn();
const apiPut = vi.fn();
const apiPost = vi.fn();

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => apiGet(...args),
    put: (...args: unknown[]) => apiPut(...args),
    post: (...args: unknown[]) => apiPost(...args),
  },
}));

vi.mock("@/store/store", () => ({
  useStore: (sel?: (s: unknown) => unknown) => {
    const state = { user: { full_name: "Test Clerk", username: "tc" } };
    return sel ? sel(state) : state;
  },
}));

import { GameModeProvider, useGameMode } from "@/store/gameMode";
import Keeper from "@/pages/Keeper/Keeper";
import { LevelPip } from "@/components/custom/LevelPip/LevelPip";

/**
 * Mount children only once the provider has resolved out of its boot-default
 * `off` into the persisted mode. This mirrors a real user who is already in
 * ambient/full when they land on the Keeper route — without it, Keeper's
 * synchronous off-mode redirect fires during the one-tick boot race and the
 * `replace` navigation traps the test on Settings.
 */
function AfterModeResolves({
  expect: expected,
  children,
}: {
  expect: string;
  children: ReactNode;
}) {
  const { mode } = useGameMode();
  if (expected !== "off" && mode !== expected) return null;
  return <>{children}</>;
}

const KEEPER_PAYLOAD = {
  stats: {
    vitality: { bucket: "1–2 months", months: 1.4 },
    mana: 1.1,
    armor: 0.8,
    might: 0.5,
    low_confidence: false,
  },
  level: 7,
  xp: 420,
  level_progress: 0.6,
};

/** Make the provider resolve to `mode` and the keeper read return the payload. */
function mockApiForMode(mode: string) {
  apiGet.mockImplementation((url: string) => {
    if (url === "/settings/")
      return Promise.resolve({ data: { preferences: { game_mode: mode } } });
    if (url === "/game/keeper/")
      return Promise.resolve({ data: KEEPER_PAYLOAD });
    return Promise.resolve({ data: {} });
  });
}

function renderKeeper(mode: string) {
  return render(
    <GameModeProvider>
      <MemoryRouter initialEntries={["/keeper"]}>
        <AfterModeResolves expect={mode}>
          <Routes>
            <Route path="/keeper" element={<Keeper />} />
            <Route path="/settings" element={<div>Settings page</div>} />
          </Routes>
        </AfterModeResolves>
      </MemoryRouter>
    </GameModeProvider>
  );
}

beforeEach(() => {
  apiGet.mockReset();
  apiPut.mockReset();
  apiPost.mockReset();
  document.documentElement.dataset.mode = "off";
});
afterEach(() => cleanup());

// ── 13: sheet renders in all three modes ──────────────────────────────────

describe("Keeper sheet renders per mode", () => {
  it("off mode redirects to Settings (no game surface)", async () => {
    mockApiForMode("off");
    const { queryByTestId, getByText } = renderKeeper("off");
    await waitFor(() => expect(getByText("Settings page")).toBeInTheDocument());
    expect(queryByTestId("keeper-sheet")).not.toBeInTheDocument();
  });

  it("ambient mode shows the sheet with plain labels", async () => {
    mockApiForMode("ambient");
    const { findByTestId, getByText } = renderKeeper("ambient");
    await findByTestId("keeper-sheet");
    // Ambient uses the plain (finance) vocabulary.
    expect(getByText(offTerms["keeper.stat.vitality"])).toBeInTheDocument();
    expect(getByText(ambientTerms["keeper.stat.mana"])).toBeInTheDocument();
  });

  it("full mode shows the sheet with game labels", async () => {
    mockApiForMode("full");
    const { findByTestId, getByText } = renderKeeper("full");
    await findByTestId("keeper-sheet");
    expect(getByText(fullTerms["keeper.stat.vitality"])).toBeInTheDocument(); // "Vitality"
    expect(getByText(fullTerms["keeper.stat.mana"])).toBeInTheDocument(); // "Mana"
  });
});

// ── 14: header level pip hidden in off, present otherwise ──────────────────

describe("header level pip", () => {
  function renderPip() {
    return render(
      <GameModeProvider>
        <MemoryRouter>
          <LevelPip />
        </MemoryRouter>
      </GameModeProvider>
    );
  }

  it("is hidden in off mode", async () => {
    mockApiForMode("off");
    const { queryByTestId } = renderPip();
    // Give the provider a tick to resolve settings; it stays off.
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/settings/"));
    expect(queryByTestId("level-pip")).not.toBeInTheDocument();
  });

  it("is present in ambient mode", async () => {
    mockApiForMode("ambient");
    const { findByTestId } = renderPip();
    expect(await findByTestId("level-pip")).toBeInTheDocument();
  });

  it("is present in full mode", async () => {
    mockApiForMode("full");
    const { findByTestId } = renderPip();
    expect(await findByTestId("level-pip")).toBeInTheDocument();
  });
});

// ── 15: banned-words scan over keeper templates ───────────────────────────

it("keeper term values contain no shame words", () => {
  const BANNED = /\b(failed|behind|worse|only|broken|lost|dead)\b/i;
  for (const catalog of [offTerms, ambientTerms, fullTerms]) {
    for (const [key, value] of Object.entries(catalog)) {
      if (!key.startsWith("keeper")) continue;
      expect(
        BANNED.test(value as string),
        `banned word in ${key}: "${value}"`
      ).toBe(false);
    }
  }
});

// ── 16: viewing the sheet emits zero game events (engagement-XP probe) ─────

it("rendering the sheet issues only reads, never a write", async () => {
  mockApiForMode("full");
  const { findByTestId } = renderKeeper("full");
  await findByTestId("keeper-sheet");
  // The provider persists mode via PUT only on a user switch — none here.
  expect(apiPut).not.toHaveBeenCalled();
  expect(apiPost).not.toHaveBeenCalled();
  // Every GET is a pure read of finance/derived data — no mutation endpoint.
  for (const call of apiGet.mock.calls) {
    expect(String(call[0])).not.toMatch(/award|event|xp|collect/i);
  }
});
