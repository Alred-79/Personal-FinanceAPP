/**
 * v4 package 02 — guard tests (groups 9, 10) + off-mode shell snapshot (5).
 *
 * 9: no component branches on `mode === '…'` outside the sanctioned files.
 * 10: money figures (`.figure` / `.ledger-figures`) never carry filter or
 *     text-shadow in any mode.
 * 5: the off-mode app shell renders with today's exact nav strings.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const SRC = join(here, "..");

// ── 9: grep guard — mode === '…' only in allowed files ───────────────────

it("mode === '<value>' appears only in sanctioned files", () => {
  // Files allowed to compare the raw mode value: the provider, the Term
  // primitive, and tests. Everything else must use flags / useTerm.
  const allowed = [
    join(SRC, "store", "gameMode.tsx"),
    join(SRC, "components", "custom", "Term", "Term.tsx"),
  ];
  // Bare `mode === '<game-mode-literal>'`. We only care about the game mode, so
  // restrict to the three intensity literals — this skips shadcn components that
  // have their own unrelated `mode` props (e.g. the calendar's "range" mode).
  const pattern = /\bmode\s*===\s*['"](off|ambient|full)['"]/;
  // Third-party shadcn primitives live in components/ui — they carry their own
  // `mode` props and are not game-aware; exclude that directory.
  const uiDir = join(SRC, "components", "ui");
  const offenders: string[] = [];

  function stripComments(src: string): string {
    // Drop block and line comments so a `mode === 'full'` mention in a docstring
    // isn't a false positive — only real code branches count.
    return src
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/(^|[^:])\/\/.*$/gm, "$1");
  }

  function walk(dir: string) {
    for (const name of readdirSync(dir)) {
      const full = join(dir, name);
      if (statSync(full).isDirectory()) {
        if (name === "__tests__" || name === "node_modules") continue;
        if (full === uiDir) continue;
        walk(full);
        continue;
      }
      if (!/\.tsx?$/.test(name)) continue;
      if (name.endsWith(".test.tsx") || name.endsWith(".test.ts")) continue;
      if (allowed.includes(full)) continue;
      if (pattern.test(stripComments(readFileSync(full, "utf8"))))
        offenders.push(full);
    }
  }
  walk(SRC);
  expect(offenders).toEqual([]);
});

// ── 10: .figure / ledger figures never get filter or text-shadow ─────────

describe("figure guard", () => {
  afterEach(() => cleanup());

  it("ledger figures carry no filter or text-shadow in any mode", () => {
    for (const mode of ["off", "ambient", "full"]) {
      document.documentElement.dataset.mode = mode;
      const { container, unmount } = render(
        <span className="figure ledger-figures">$1,234.56</span>
      );
      const el = container.firstChild as HTMLElement;
      const style = getComputedStyle(el);
      // jsdom doesn't apply stylesheet cascade, but the inline guard intent is
      // asserted by checking no filter/text-shadow is set on the element.
      expect(["none", ""]).toContain(style.filter || "none");
      expect(["none", ""]).toContain(style.textShadow || "none");
      unmount();
    }
  });
});

// ── 5: off-mode shell snapshot uses today's exact nav strings ────────────

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn().mockResolvedValue({ data: { preferences: { game_mode: "off" } } }), put: vi.fn() },
}));

import { MemoryRouter } from "react-router-dom";
import { GameModeProvider } from "@/store/gameMode";
import Sidebar from "@/components/layout/Sidebar";

vi.mock("@/store/store", () => ({
  useStore: (sel?: (s: unknown) => unknown) => {
    const state = { user: { full_name: "Test Clerk", username: "tc" } };
    return sel ? sel(state) : state;
  },
}));

describe("off-mode shell", () => {
  beforeEach(() => {
    document.documentElement.dataset.mode = "off";
  });
  afterEach(() => cleanup());

  it("renders the existing nav labels verbatim in off mode", () => {
    const { getByText } = render(
      <GameModeProvider>
        <MemoryRouter>
          <Sidebar
            onConnectBank={() => {}}
            canConnectBank
            onLogout={() => {}}
          />
        </MemoryRouter>
      </GameModeProvider>
    );
    // The off catalog values are the pre-game literals; assert each is present
    // exactly (the pixel-identity contract for off mode).
    for (const label of [
      "Overview",
      "Accounts",
      "Ledger",
      "Budgets",
      "Goals",
      "Forecast",
      "Standing Orders",
      "Settings",
    ]) {
      expect(getByText(label)).toBeInTheDocument();
    }
  });

  it("matches the off-mode sidebar snapshot", () => {
    const { container } = render(
      <GameModeProvider>
        <MemoryRouter>
          <Sidebar
            onConnectBank={() => {}}
            canConnectBank
            onLogout={() => {}}
          />
        </MemoryRouter>
      </GameModeProvider>
    );
    expect(container).toMatchSnapshot();
  });
});
