/**
 * v4 package 02 — game-mode system tests (client groups 1-10).
 *
 * The provider boots in off (no game-chrome flash), setMode swaps tokens +
 * terms live and PATCHes once, useTerm/<Term/> resolve and reveal, the catalog
 * parity test forces all three catalogs to stay in sync, and the grep / figure
 * guards keep mode-branching and number-decoration contained.
 */
import { it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, waitFor, cleanup } from "@testing-library/react";

// Mock the api module the provider/selector use to load + persist the mode.
const apiGet = vi.fn();
const apiPut = vi.fn();
vi.mock("@/lib/api", () => ({
  default: { get: (...a: unknown[]) => apiGet(...a), put: (...a: unknown[]) => apiPut(...a) },
}));

import {
  GameModeProvider,
  useGameMode,
  useTerm,
} from "@/store/gameMode";
import { useStore } from "@/store/store";
import { Term } from "@/components/custom/Term/Term";
import { ScanlineOverlay } from "@/components/custom/ScanlineOverlay/ScanlineOverlay";
import offTerms from "@/terms/terms.off.json";
import ambientTerms from "@/terms/terms.ambient.json";
import fullTerms from "@/terms/terms.full.json";

beforeEach(() => {
  apiGet.mockReset();
  apiPut.mockReset();
  apiGet.mockResolvedValue({ data: { preferences: { game_mode: "off" } } });
  apiPut.mockResolvedValue({ data: {} });
  document.documentElement.removeAttribute("data-mode");
});

afterEach(() => cleanup());

// A small harness exposing the provider value to assertions.
function Harness({ onReady }: { onReady: (v: ReturnType<typeof useGameMode>) => void }) {
  const value = useGameMode();
  onReady(value);
  return <div data-testid="mode">{value.mode}</div>;
}

// ── 1: boots in off, no full flash ───────────────────────────────────────

it("boots in off before settings resolve (no full-mode flash)", async () => {
  // Make the settings load hang so we observe the pre-resolve state.
  apiGet.mockReturnValue(new Promise(() => {}));
  render(
    <GameModeProvider>
      <Harness onReady={() => {}} />
    </GameModeProvider>
  );
  expect(screen.getByTestId("mode").textContent).toBe("off");
  expect(document.documentElement.dataset.mode).toBe("off");
});

// ── 2: setMode swaps attribute + terms + PATCHes once ────────────────────

it("setMode('full') sets data-mode, swaps terms, and PATCHes once", async () => {
  let api: ReturnType<typeof useGameMode> | null = null;
  render(
    <GameModeProvider>
      <Harness onReady={(v) => (api = v)} />
    </GameModeProvider>
  );
  await waitFor(() => expect(api).not.toBeNull());

  act(() => api!.setMode("full"));
  await waitFor(() =>
    expect(document.documentElement.dataset.mode).toBe("full")
  );
  expect(api!.term("nav.budgets")).toBe(fullTerms["nav.budgets"]);
  expect(apiPut).toHaveBeenCalledTimes(1);
  expect(apiPut).toHaveBeenCalledWith("/settings/preferences/", {
    game_mode: "full",
  });
});

// ── 3: useTerm resolves per mode + falls back to off ─────────────────────

function TermProbe({ k }: { k: string }) {
  return <span data-testid="term">{useTerm(k)}</span>;
}

it("useTerm returns per-mode value and falls back to off for unknown keys", async () => {
  let api: ReturnType<typeof useGameMode> | null = null;
  render(
    <GameModeProvider>
      <Harness onReady={(v) => (api = v)} />
      <TermProbe k="nav.budgets" />
    </GameModeProvider>
  );
  await waitFor(() => expect(api).not.toBeNull());
  expect(screen.getByTestId("term").textContent).toBe("Budgets"); // off

  act(() => api!.setMode("full"));
  await waitFor(() =>
    expect(screen.getByTestId("term").textContent).toBe(
      fullTerms["nav.budgets"]
    )
  );
  // Unknown key falls back to the off catalog value, then the key itself.
  expect(api!.term("does.not.exist")).toBe("does.not.exist");
});

// ── 4: <Term/> reveals the plain term in full mode ───────────────────────

it("<Term/> exposes the off-mode term via title/aria-label in full mode", async () => {
  let api: ReturnType<typeof useGameMode> | null = null;
  render(
    <GameModeProvider>
      <Harness onReady={(v) => (api = v)} />
      <div data-testid="wrap">
        <Term k="nav.budgets" />
      </div>
    </GameModeProvider>
  );
  await waitFor(() => expect(api).not.toBeNull());
  // off mode: bare text, no reveal wrapper.
  expect(screen.getByTestId("wrap").querySelector("[data-term]")).toBeNull();

  act(() => api!.setMode("full"));
  await waitFor(() => {
    const el = screen.getByTestId("wrap").querySelector("[data-term]");
    expect(el).not.toBeNull();
    expect(el).toHaveAttribute("title", "Budgets");
    expect(el).toHaveAttribute("aria-label", "Budgets");
  });
});

// ── 6: ScanlineOverlay only in full ──────────────────────────────────────

it("ScanlineOverlay is absent in off/ambient and present in full", async () => {
  let api: ReturnType<typeof useGameMode> | null = null;
  render(
    <GameModeProvider>
      <Harness onReady={(v) => (api = v)} />
      <ScanlineOverlay />
    </GameModeProvider>
  );
  await waitFor(() => expect(api).not.toBeNull());
  expect(screen.queryByTestId("scanline-overlay")).toBeNull();

  act(() => api!.setMode("ambient"));
  await waitFor(() => expect(api!.mode).toBe("ambient"));
  expect(screen.queryByTestId("scanline-overlay")).toBeNull();

  act(() => api!.setMode("full"));
  await waitFor(() =>
    expect(screen.queryByTestId("scanline-overlay")).not.toBeNull()
  );
});

// ── 7: catalog parity (the mechanism forcing future packages to fill 3) ──

it("all three term catalogs have an identical key set", () => {
  const off = Object.keys(offTerms).sort();
  const ambient = Object.keys(ambientTerms).sort();
  const full = Object.keys(fullTerms).sort();
  expect(ambient).toEqual(off);
  expect(full).toEqual(off);
});

// ── 8: mode persists across remount (reads PATCHed value) ────────────────

it("provider remount reads the persisted mode from the server", async () => {
  apiGet.mockResolvedValue({
    data: { preferences: { game_mode: "ambient" } },
  });
  let api: ReturnType<typeof useGameMode> | null = null;
  render(
    <GameModeProvider>
      <Harness onReady={(v) => (api = v)} />
    </GameModeProvider>
  );
  await waitFor(() => expect(api?.mode).toBe("ambient"));
  expect(document.documentElement.dataset.mode).toBe("ambient");
});

it("normal settings hydration applies the persisted game mode after login", async () => {
  apiGet
    .mockResolvedValueOnce({ data: { preferences: { game_mode: "off" } } })
    .mockResolvedValueOnce({
      data: {
        preferences: {
          game_mode: "ambient",
          spend_warning: 70,
          savings_percent: 20,
        },
        features: {},
      },
    });
  useStore.setState({ settingsLoaded: false, settingsError: false });
  let modeApi: ReturnType<typeof useGameMode> | null = null;
  render(
    <GameModeProvider>
      <Harness onReady={(value) => (modeApi = value)} />
    </GameModeProvider>
  );
  await waitFor(() => expect(modeApi?.mode).toBe("off"));

  await act(async () => {
    await useStore.getState().fetchUserSettings();
  });

  await waitFor(() => expect(modeApi?.mode).toBe("ambient"));
  expect(useStore.getState().settingsLoaded).toBe(true);
});
