import { describe, it, expect, beforeEach } from "vitest";
import {
  suggestionForPath,
  isSilenced,
  silenceNudges,
  hasNudged,
  markNudged,
  nudgeCount,
  MAX_SESSION_NUDGES,
} from "@/hooks/useClerkSuggestions";

beforeEach(() => {
  sessionStorage.clear();
});

describe("suggestionForPath", () => {
  it("resolves an exact section", () => {
    expect(suggestionForPath("/rules")?.label).toMatch(/rule/i);
    expect(suggestionForPath("/rules")?.prompt).toContain("rule");
  });

  it("falls back to the longest route prefix for nested paths", () => {
    // a deep link under /rules still gets the Rule Book offer
    expect(suggestionForPath("/rules/42")?.label).toBe(
      suggestionForPath("/rules")?.label
    );
  });

  it("returns null for unknown sections", () => {
    expect(suggestionForPath("/keeper")).toBeNull();
    expect(suggestionForPath("/totally-unknown")).toBeNull();
  });

  it("marks the home greeting as hover-only (auto: false)", () => {
    expect(suggestionForPath("/")?.auto).toBe(false);
  });

  it("never pre-sends — prompts are starters, not commands", () => {
    // the forecast/rules starters are deliberately unfinished (trailing space)
    expect(suggestionForPath("/forecast")?.prompt).toBe("What if ");
  });
});

describe("nudge frequency model (session-scoped)", () => {
  it("starts clean", () => {
    expect(isSilenced()).toBe(false);
    expect(hasNudged("/rules")).toBe(false);
    expect(nudgeCount()).toBe(0);
  });

  it("records a nudge once per route and counts distinct sections", () => {
    markNudged("/rules");
    markNudged("/rules"); // idempotent
    markNudged("/budgets");
    expect(hasNudged("/rules")).toBe(true);
    expect(hasNudged("/goals")).toBe(false);
    expect(nudgeCount()).toBe(2);
  });

  it("caps distinct auto-nudges at MAX_SESSION_NUDGES", () => {
    ["/a", "/b", "/c", "/d", "/e"].forEach(markNudged);
    // the orchestrator stops scheduling once nudgeCount() >= MAX_SESSION_NUDGES
    expect(nudgeCount()).toBeGreaterThanOrEqual(MAX_SESSION_NUDGES);
  });

  it("silences all future auto-nudges with one dismiss", () => {
    expect(isSilenced()).toBe(false);
    silenceNudges();
    expect(isSilenced()).toBe(true);
  });
});
