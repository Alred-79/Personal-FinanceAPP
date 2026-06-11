import { describe, it, expect } from "vitest";
import { formatCurrency, categoryColor } from "@/lib/format";

describe("formatCurrency", () => {
  it("formats a positive value", () => {
    expect(formatCurrency(1234.56)).toBe("$1,234.56");
  });

  it("formats zero", () => {
    expect(formatCurrency(0)).toBe("$0.00");
  });

  it("formats a negative value", () => {
    expect(formatCurrency(-50.5)).toBe("-$50.50");
  });

  it("rounds sub-cent values down", () => {
    expect(formatCurrency(0.001)).toBe("$0.00");
  });

  it("formats large amounts with commas", () => {
    expect(formatCurrency(1000000)).toBe("$1,000,000.00");
  });

  it("formats a round dollar amount", () => {
    expect(formatCurrency(42)).toBe("$42.00");
  });
});

describe("categoryColor", () => {
  it("returns a string for a known category", () => {
    const color = categoryColor("Food");
    expect(typeof color).toBe("string");
    expect(color.length).toBeGreaterThan(0);
  });

  it("Food returns the phosphor green value", () => {
    expect(categoryColor("Food")).toBe("hsl(150, 100%, 50%)");
  });

  it("Transport returns the amber value", () => {
    expect(categoryColor("Transport")).toBe("hsl(46, 100%, 50%)");
  });

  it("returns a string for an unknown category", () => {
    const color = categoryColor("QuantumTeleportation");
    expect(typeof color).toBe("string");
    expect(color.length).toBeGreaterThan(0);
  });

  it("is deterministic for unknown categories", () => {
    expect(categoryColor("ZZZ")).toBe(categoryColor("ZZZ"));
  });

  it("does not throw when fallback is provided", () => {
    expect(() => categoryColor("Unknown", "hsl(0,0%,50%)")).not.toThrow();
  });

  it("returns a valid hsl string for all known categories", () => {
    const known = [
      "Food", "Transport", "Entertainment", "Health",
      "Shopping", "Utilities", "Housing", "Income",
    ];
    for (const cat of known) {
      expect(categoryColor(cat)).toMatch(/^hsl\(/);
    }
  });
});
