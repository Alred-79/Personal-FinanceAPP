/**
 * v4 package 08 — the Expedition (client).
 *
 * The two-homes IA: full mode's home is the Expedition map; off/ambient stay
 * Overview — routing reads ONLY the mode flag. The Expedition view renders the
 * same DOM structure in every mode (only the skin/terms change), and the map
 * page exists in all modes (fork-smell law).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { type ReactNode } from "react";

const apiGet = vi.fn();
vi.mock("@/lib/api", () => ({
  default: { get: (...a: unknown[]) => apiGet(...a), post: vi.fn(), put: vi.fn() },
}));

// Home is a pure ROUTER between two heavy pages; mock both children so we test
// only which one Home picks (not their internals, which need full store wiring).
vi.mock("@/pages/Overview/Overview", () => ({
  default: () => <div data-testid="overview-stub" />,
}));
vi.mock("@/pages/Expedition/Expedition", async (orig) => {
  const actual = (await orig()) as Record<string, unknown>;
  return { ...actual, default: () => <div data-testid="expedition-stub" /> };
});

import { GameModeProvider, useGameMode } from "@/store/gameMode";
import Home from "@/pages/Home/Home";
import { ExpeditionView } from "@/pages/Expedition/Expedition";

const MAP = {
  month: "2026-06",
  acts: [{ index: 1, start: "2026-06-01", end: "2026-06-30", forks: [] }],
  nodes: [
    { kind: "bill", day: "2026-06-05", label: "Rent" },
    { kind: "rest", day: "2026-06-13", label: "A quiet stretch" },
  ],
};

function mockMode(mode: string) {
  apiGet.mockImplementation((url: string) => {
    if (url === "/settings/") return Promise.resolve({ data: { preferences: { game_mode: mode } } });
    if (url === "/game/expedition/") return Promise.resolve({ data: { map: MAP } });
    return Promise.resolve({ data: {} });
  });
}

function AfterMode({ expect: want, children }: { expect: string; children: ReactNode }) {
  const { mode } = useGameMode();
  if (want !== "off" && mode !== want) return null;
  return <>{children}</>;
}

beforeEach(() => {
  apiGet.mockReset();
  document.documentElement.dataset.mode = "off";
});
afterEach(() => cleanup());

describe("two-homes IA", () => {
  it("full mode home routes to the Expedition", async () => {
    mockMode("full");
    const { findByTestId } = render(
      <GameModeProvider>
        <MemoryRouter>
          <AfterMode expect="full"><Home /></AfterMode>
        </MemoryRouter>
      </GameModeProvider>
    );
    expect(await findByTestId("expedition-stub")).toBeInTheDocument();
  });

  it("off/ambient home routes to Overview, not the Expedition", async () => {
    mockMode("ambient");
    const { findByTestId, queryByTestId } = render(
      <GameModeProvider>
        <MemoryRouter>
          <AfterMode expect="ambient"><Home /></AfterMode>
        </MemoryRouter>
      </GameModeProvider>
    );
    expect(await findByTestId("overview-stub")).toBeInTheDocument();
    expect(queryByTestId("expedition-stub")).not.toBeInTheDocument();
  });
});

describe("expedition view", () => {
  it("renders acts and nodes; skin differs by mode but DOM structure matches", async () => {
    // full skin
    mockMode("full");
    const full = render(
      <GameModeProvider>
        <MemoryRouter>
          <AfterMode expect="full"><ExpeditionView /></AfterMode>
        </MemoryRouter>
      </GameModeProvider>
    );
    // Wait for the async map fetch to populate before asserting nodes.
    await full.findByTestId("expedition-act");
    const fullView = full.getByTestId("expedition-view");
    expect(fullView.getAttribute("data-skin")).toBe("map");
    expect(full.getAllByTestId("node-bill").length).toBe(1);
    full.unmount();
    cleanup();

    // off skin — same structure (act + bill node present), calendar skin
    mockMode("off");
    const off = render(
      <GameModeProvider>
        <MemoryRouter><ExpeditionView /></MemoryRouter>
      </GameModeProvider>
    );
    await off.findByTestId("expedition-act");
    const offView = off.getByTestId("expedition-view");
    expect(offView.getAttribute("data-skin")).toBe("calendar");
    expect(off.getAllByTestId("node-bill").length).toBe(1);
  });
});
