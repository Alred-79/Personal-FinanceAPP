/**
 * v4 package 03 — money spine client tests (groups 16-18).
 *
 * The glanceable number is identical across modes (only the label changes), the
 * tab title follows the format rules and the settings toggle, and the hero
 * surface carries no category-remaining bars (the TFI guard).
 */
import { it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn().mockResolvedValue({ data: { preferences: { game_mode: "off" } } }), put: vi.fn() },
}));

// Drive the store's safeToSpend selector.
const storeState: Record<string, unknown> = {};
vi.mock("@/store/store", () => ({
  useStore: (sel?: (s: unknown) => unknown) =>
    sel ? sel(storeState) : storeState,
}));

import {
  SafeToSpend,
  formatSafeToSpend,
} from "@/components/custom/SafeToSpend/SafeToSpend";

function setS2S(available: number | null) {
  storeState.safeToSpend =
    available === null
      ? null
      : { available, horizon_end: "2026-06-20", days_remaining: 19 };
}

beforeEach(() => {
  setS2S(412);
  document.documentElement.dataset.mode = "off";
  document.title = "";
});
afterEach(() => cleanup());

// ── format rules (17) ────────────────────────────────────────────────────

it("formats whole dollars, no cents, sign-aware", () => {
  expect(formatSafeToSpend(412)).toBe("$412");
  expect(formatSafeToSpend(1234.56)).toBe("$1,235");
  expect(formatSafeToSpend(-42)).toBe("-$42");
  expect(formatSafeToSpend(0)).toBe("$0");
});

// ── 16: number identical across modes, only label changes ────────────────

it("renders the identical number in every mode", () => {
  const numbers: string[] = [];
  for (const mode of ["off", "ambient", "full"]) {
    document.documentElement.dataset.mode = mode;
    const { getByTestId, unmount } = render(<SafeToSpend updateTabTitle={false} />);
    const figure = getByTestId("safe-to-spend").querySelector(".figure");
    numbers.push(figure?.textContent ?? "");
    unmount();
  }
  // Every mode shows the same number string.
  expect(new Set(numbers)).toEqual(new Set(["$412"]));
});

// ── 17: tab title updates + toggle ───────────────────────────────────────

it("updates the tab title on render and respects the toggle", () => {
  const { unmount } = render(<SafeToSpend updateTabTitle />);
  expect(document.title).toBe("$412 · The Ledger");
  unmount();

  document.title = "";
  render(<SafeToSpend updateTabTitle={false} />);
  expect(document.title).toBe(""); // toggle off → no tab-title write
});

// ── 18: TFI guard — no category-remaining bars on the hero ───────────────

it("hero surface contains no category-remaining bars", () => {
  const { getByTestId } = render(<SafeToSpend updateTabTitle={false} />);
  const hero = getByTestId("safe-to-spend");
  // No progress/meter elements (the category-remaining bars we must not show).
  expect(hero.querySelector('[role="progressbar"]')).toBeNull();
  expect(hero.querySelector("progress")).toBeNull();
  // Exactly one money figure on this surface.
  expect(hero.querySelectorAll(".figure").length).toBe(1);
});

// ── negative shows alert style, never the boss accent ────────────────────

it("a negative number uses the alert style, not the boss/red-game accent", () => {
  setS2S(-25);
  const { getByTestId } = render(<SafeToSpend updateTabTitle={false} />);
  const figure = getByTestId("safe-to-spend").querySelector(".figure");
  // Uses the standard destructive token; never the game boss accent class.
  expect(figure?.className).toContain("text-destructive");
  expect(figure?.className).not.toContain("boss");
});
