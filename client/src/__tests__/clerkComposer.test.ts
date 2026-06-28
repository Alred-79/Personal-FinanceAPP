import { describe, it, expect } from "vitest";
import {
  parseSlash,
  filterSlash,
  ghostCompletion,
  SLASH_COMMANDS,
} from "@/lib/clerkComposer";

describe("parseSlash", () => {
  it("opens while the whole input is a single slash token", () => {
    expect(parseSlash("/")).toEqual({ open: true, query: "" });
    expect(parseSlash("/ru")).toEqual({ open: true, query: "ru" });
    expect(parseSlash("/RULE")).toEqual({ open: true, query: "rule" });
  });

  it("closes once there is a space or the slash isn't at the start", () => {
    expect(parseSlash("/rule something").open).toBe(false);
    expect(parseSlash("a/b").open).toBe(false);
    expect(parseSlash("hello").open).toBe(false);
    expect(parseSlash("").open).toBe(false);
  });
});

describe("filterSlash", () => {
  it("returns all commands for an empty query", () => {
    expect(filterSlash("")).toHaveLength(SLASH_COMMANDS.length);
  });

  it("matches by command token or label", () => {
    expect(filterSlash("ru").some((c) => c.cmd === "rule")).toBe(true);
    expect(filterSlash("clear").some((c) => c.action === "clear")).toBe(true);
    // "review" appears in a label (Review subscriptions)
    expect(filterSlash("review").some((c) => c.cmd === "subscriptions")).toBe(true);
  });

  it("returns nothing for an unmatched query", () => {
    expect(filterSlash("zzzzz")).toHaveLength(0);
  });
});

describe("ghostCompletion", () => {
  it("completes a known prompt from its prefix", () => {
    expect(ghostCompletion("How much have I")).toBe("How much have I spent this week?");
  });

  it("is suppressed for slash input, short input, and non-matches", () => {
    expect(ghostCompletion("/ru")).toBeNull();
    expect(ghostCompletion("ab")).toBeNull();
    expect(ghostCompletion("zzzz nonsense")).toBeNull();
  });

  it("does not complete a string that already equals a corpus entry", () => {
    expect(ghostCompletion("How much have I spent this week?")).toBeNull();
  });

  it("prefers caller-supplied extras (the section starter) first", () => {
    expect(ghostCompletion("Tell me", ["Tell me about my budgets"])).toBe(
      "Tell me about my budgets"
    );
  });
});
