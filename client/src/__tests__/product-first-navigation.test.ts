import { describe, expect, it } from "vitest";
import { NAV_ITEMS, NAV_GROUPS } from "@/components/layout/nav";
import off from "@/terms/terms.off.json";
import ambient from "@/terms/terms.ambient.json";
import full from "@/terms/terms.full.json";

describe("product-first navigation", () => {
  it("keeps four literal daily destinations first", () => {
    expect(NAV_ITEMS.slice(0, 4).map((item) => [item.label, item.to, item.group])).toEqual([
      ["Overview", "/", "primary"],
      ["Decisions", "/forecast", "primary"],
      ["Upcoming", "/subscriptions", "primary"],
      ["Transactions", "/transactions", "primary"],
    ]);
    expect(NAV_GROUPS.map((group) => group.label)).toEqual(["Daily", "Plan", "Review", "More"]);
  });

  it("uses the same literal task labels in every terminology catalog", () => {
    for (const catalog of [off, ambient, full]) {
      expect(catalog["nav.transactions"]).toBe("Transactions");
      expect(catalog["nav.forecast"]).toBe("Decisions");
      expect(catalog["nav.subscriptions"]).toBe("Upcoming");
      expect(catalog["nav.almanac"]).toBe("Insights");
      expect(catalog["nav.reconcile"]).toBe("Import & reconcile");
    }
  });
});
