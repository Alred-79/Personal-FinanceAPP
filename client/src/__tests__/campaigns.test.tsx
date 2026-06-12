/**
 * v4 package 10 — campaigns + outcomes (client).
 *
 * The countdown ban (scan-enforced over the campaign surfaces and term
 * catalogs), the mode law (route renders in every mode; off redirects), the
 * kill-switch/holdout quiet state, and the internal outcomes page.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { type ReactNode } from "react";

const apiGet = vi.fn();
vi.mock("@/lib/api", () => ({
  default: { get: (...a: unknown[]) => apiGet(...a), post: vi.fn(), put: vi.fn() },
}));

import { GameModeProvider, useGameMode } from "@/store/gameMode";
import Campaigns from "@/pages/Campaigns/Campaigns";
import Outcomes from "@/pages/Outcomes/Outcomes";
import offTerms from "@/terms/terms.off.json";
import ambientTerms from "@/terms/terms.ambient.json";
import fullTerms from "@/terms/terms.full.json";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

const CAMPAIGN = {
  quarter: "2026-Q2",
  arc_key: "the_long_thaw",
  status: "active",
  rank: "C",
  lifetime_prestige: 9,
  milestones: [
    { key: "green_week_1", label_term: "campaign.milestone.green_week_1", granted: true },
    { key: "month_sealed_1", label_term: "campaign.milestone.month_sealed_1", granted: false },
  ],
};

function mockMode(mode: string, campaign: unknown) {
  apiGet.mockImplementation((url: string) => {
    if (url === "/settings/")
      return Promise.resolve({ data: { preferences: { game_mode: mode } } });
    if (url === "/game/campaigns/")
      return Promise.resolve({ data: { campaign } });
    if (url === "/game/challenges/")
      return Promise.resolve({ data: { challenges: [], candidates: [] } });
    if (url === "/game/outcomes/")
      return Promise.resolve({
        data: {
          comparison: {
            hard_day_action_rate: {
              game: { n: 12, mean: 0.61, ci_low: 0.5, ci_high: 0.72 },
              holdout: { n: 3, mean: 0.55, ci_low: 0.3, ci_high: 0.8 },
            },
          },
          honesty_footer: {
            sample_sizes: { game: 12, holdout: 3 },
            caveats: ["Internal v0.", "Small samples are wide and shown as such."],
          },
        },
      });
    return Promise.resolve({ data: {} });
  });
}

function AfterMode({ expect: want, children }: { expect: string; children: ReactNode }) {
  const { mode } = useGameMode();
  if (want !== "off" && mode !== want) return null;
  return <>{children}</>;
}

function renderCampaigns(mode: string) {
  return render(
    <GameModeProvider>
      <MemoryRouter initialEntries={["/campaigns"]}>
        <AfterMode expect={mode}>
          <Routes>
            <Route path="/campaigns" element={<Campaigns />} />
            <Route path="/settings" element={<div data-testid="settings-page" />} />
          </Routes>
        </AfterMode>
      </MemoryRouter>
    </GameModeProvider>
  );
}

beforeEach(() => {
  apiGet.mockReset();
  document.documentElement.dataset.mode = "off";
});
afterEach(() => cleanup());

// ── the countdown ban (spec test 4, client side) ────────────────────────────

const COUNTDOWN_PATTERN =
  /\b(expires?|expiring|expired|last chance|hurry|countdown|time (left|remaining)|days (left|remaining)|missed)\b/i;

function stripComments(src: string): string {
  // Comments may NAME the ban; only rendered code is scanned.
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

describe("countdown scan", () => {
  it("no campaign source file renders countdown vocabulary", () => {
    const offenders: string[] = [];
    function walk(dir: string) {
      for (const name of readdirSync(dir)) {
        const full = join(dir, name);
        if (statSync(full).isDirectory()) {
          walk(full);
          continue;
        }
        if (!/\.tsx?$/.test(name)) continue;
        if (COUNTDOWN_PATTERN.test(stripComments(readFileSync(full, "utf8"))))
          offenders.push(full);
      }
    }
    walk(join(SRC, "pages", "Campaigns"));
    expect(offenders).toEqual([]);
  });

  it("no campaign/challenge term in any catalog carries countdown vocabulary", () => {
    for (const catalog of [offTerms, ambientTerms, fullTerms]) {
      for (const [key, value] of Object.entries(catalog)) {
        if (!key.startsWith("campaign.") && !key.startsWith("challenge.")) continue;
        expect(
          COUNTDOWN_PATTERN.test(value as string),
          `${key} = ${value}`
        ).toBe(false);
      }
    }
  });
});

// ── the mode law: route exists everywhere; off redirects ────────────────────

describe("campaigns mode law", () => {
  it("off mode redirects to settings (route still exists)", async () => {
    mockMode("off", null);
    const { findByTestId } = renderCampaigns("off");
    await findByTestId("settings-page");
  });

  it("full mode renders rank and the milestone track", async () => {
    mockMode("full", CAMPAIGN);
    const { findByTestId } = renderCampaigns("full");
    const rank = await findByTestId("campaign-rank");
    expect(rank.textContent).toBe("C");
    await findByTestId("milestone-track");
    await findByTestId("milestone-green_week_1");
  });

  it("ambient mode renders too (no full-only fork)", async () => {
    mockMode("ambient", CAMPAIGN);
    const { findByTestId } = renderCampaigns("ambient");
    await findByTestId("campaigns-page");
  });
});

// ── kill switch / holdout: the API's null renders the quiet state ───────────

describe("kill-switch / holdout quiet state", () => {
  it("a null campaign renders nothing loud — no error, no countdown", async () => {
    mockMode("full", null);
    const { findByTestId, queryByTestId } = renderCampaigns("full");
    await findByTestId("campaigns-page");
    expect(queryByTestId("milestone-track")).not.toBeInTheDocument();
    expect(queryByTestId("campaign-rank")).not.toBeInTheDocument();
  });
});

// ── the internal outcomes page ──────────────────────────────────────────────

describe("outcomes v0 (internal)", () => {
  it("renders cohort comparison with CIs and the honesty footer in every mode", async () => {
    for (const mode of ["off", "ambient", "full"]) {
      mockMode(mode, null);
      const { findByTestId, unmount } = render(
        <GameModeProvider>
          <MemoryRouter initialEntries={["/outcomes"]}>
            <Routes>
              <Route path="/outcomes" element={<Outcomes />} />
            </Routes>
          </MemoryRouter>
        </GameModeProvider>
      );
      const table = await findByTestId("metric-hard_day_action_rate");
      expect(table.textContent).toContain("0.6100");
      expect(table.textContent).toContain("holdout");
      const footer = await findByTestId("honesty-footer");
      expect(footer.textContent).toContain("game=12");
      expect(footer.textContent).toContain("Small samples");
      unmount();
      cleanup();
      apiGet.mockReset();
    }
  });

  it("the outcomes page carries no marketing language", () => {
    const source = readFileSync(
      join(SRC, "pages", "Outcomes", "Outcomes.tsx"), "utf8");
    for (const banned of ["amazing", "incredible", "supercharge", "unlock",
                          "transform your", "best-in-class"]) {
      expect(source.toLowerCase()).not.toContain(banned);
    }
  });
});

// ── catalog parity for the new keys (extends the package-02 contract) ───────

describe("package-10 term keys", () => {
  it("exist in all three catalogs", () => {
    const wanted = [
      "nav.campaigns", "campaign.title", "campaign.rank", "campaign.paused",
      "challenge.title", "outcomes.title",
    ];
    for (const key of wanted) {
      expect(key in offTerms, `off:${key}`).toBe(true);
      expect(key in ambientTerms, `ambient:${key}`).toBe(true);
      expect(key in fullTerms, `full:${key}`).toBe(true);
    }
  });
});
