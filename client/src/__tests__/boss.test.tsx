/**
 * v4 package 06 — debt boss (client).
 *
 * ASCII determinism (same seed → identical grid; different creditors differ),
 * the juice allowlist walk (no purchase/engagement event juices), reduced-motion
 * fallback, and the closure-card zero-$ default (numbers only with the toggle).
 */
import { describe, it, expect, vi, afterEach } from "vitest";

import { asciiCreature, asciiCreatureText, hashSeed, sizeTier } from "@/lib/asciiCreature";
import { isJuiceEvent, JUICE_EVENTS, shouldAnimate } from "@/lib/juice";
import { closureCardLines } from "@/components/custom/ClosureCard/ClosureCard";

afterEach(() => {
  vi.restoreAllMocks();
});

// ── 18: ASCII determinism ─────────────────────────────────────────────────

describe("ascii creature", () => {
  it("is deterministic: same seed → identical grid across runs", () => {
    const a = asciiCreatureText({ kind: "credit_card", name: "Chase Sapphire", balanceCents: 300000 });
    const b = asciiCreatureText({ kind: "credit_card", name: "Chase Sapphire", balanceCents: 300000 });
    expect(a).toBe(b);
  });

  it("normalizes the name (case/space-insensitive seed)", () => {
    const a = asciiCreatureText({ kind: "loan", name: "Acme Loan" });
    const b = asciiCreatureText({ kind: "loan", name: "  acme   loan " });
    expect(a).toBe(b);
  });

  it("different creditors → different grids", () => {
    const a = asciiCreatureText({ kind: "credit_card", name: "Visa" });
    const b = asciiCreatureText({ kind: "credit_card", name: "Amex" });
    expect(a).not.toBe(b);
  });

  it("is left-right mirror-symmetric", () => {
    const rows = asciiCreature({ kind: "other", name: "Wyrm", balanceCents: 50000 });
    for (const row of rows) {
      expect(row).toBe([...row].reverse().join(""));
    }
  });

  it("scales size with balance bucket", () => {
    expect(sizeTier(2_000_000)).toBeGreaterThan(sizeTier(10_000));
  });

  it("hashSeed is stable and unsigned", () => {
    expect(hashSeed("x")).toBe(hashSeed("x"));
    expect(hashSeed("x")).toBeGreaterThanOrEqual(0);
  });
});

// ── 19: juice allowlist walk ──────────────────────────────────────────────

describe("juice allowlist", () => {
  it("never celebrates a purchase or engagement event", () => {
    for (const e of ["TxnPosted", "SheetViewed", "ModeChanged", "DayClosed", "WardConsumed"]) {
      expect(isJuiceEvent(e)).toBe(false);
    }
  });

  it("celebrates only payoff events; crit/sweep are variant-gated", () => {
    expect(isJuiceEvent("BossDamaged", { crit: false })).toBe(false);
    expect(isJuiceEvent("BossDamaged", { crit: true })).toBe(true);
    expect(isJuiceEvent("RuleExecuted", { kind: "categorize" })).toBe(false);
    expect(isJuiceEvent("RuleExecuted", { kind: "sweep" })).toBe(true);
    expect(isJuiceEvent("BossDefeated")).toBe(true);
    expect(isJuiceEvent("LevelUp")).toBe(true);
  });

  it("the allowlist contains no transaction or engagement events", () => {
    for (const e of JUICE_EVENTS) {
      expect(["TxnPosted", "SheetViewed", "ModeChanged", "DayClosed"]).not.toContain(e);
    }
  });
});

// ── 20: reduced-motion ────────────────────────────────────────────────────

describe("reduced motion", () => {
  it("does not animate when prefers-reduced-motion is set", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: q.includes("reduce"),
      media: q,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    expect(shouldAnimate()).toBe(false);
  });

  it("animates when motion is allowed", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: false,
      media: q,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    expect(shouldAnimate()).toBe(true);
  });
});

// ── 12 (client): closure card zero-$ default ──────────────────────────────

describe("closure card", () => {
  it("shows no dollar amount by default", () => {
    const lines = closureCardLines({
      bossName: "The Chase Wyrm",
      kind: "credit_card",
      durationMonths: 7,
    });
    expect(lines.join(" ")).not.toContain("$");
    expect(lines.join(" ")).toContain("Defeated in 7 months");
  });

  it("includes the amount only when the toggle is on", () => {
    const lines = closureCardLines({
      bossName: "The Chase Wyrm",
      kind: "credit_card",
      durationMonths: 7,
      includeNumbers: true,
      amountPaidCents: 500000,
    });
    expect(lines.join(" ")).toContain("$5,000");
  });
});
