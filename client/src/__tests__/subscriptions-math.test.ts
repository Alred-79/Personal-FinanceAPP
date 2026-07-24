import { describe, expect, it } from "vitest";

import {
  annualBurden,
  monthlyBurden,
  possibleMonthlyBurden,
  projectedAnnual,
} from "@/lib/subscriptions";
import type { Subscription } from "@/types";

const subscription = (overrides: Partial<Subscription> = {}): Subscription => ({
  merchant: "Example",
  title: "Example",
  amount: 10,
  cadence: "monthly",
  occurrences: 4,
  last_date: "2026-07-01",
  next_date: "2026-08-01",
  ...overrides,
});

describe("subscription burden math", () => {
  it("does not apply an already-observed price increase twice", () => {
    const sub = subscription({ amount: 15, price_change_pct: 0.5, prev_amount: 10 });
    expect(projectedAnnual(sub)).toBe(180);
  });

  it("separates likely-active burden from charges needing review", () => {
    const active = subscription({ merchant: "Active", probability_alive: 0.9 });
    const dormant = subscription({ merchant: "Dormant", amount: 20, lifecycle_status: "dormant" });
    expect(monthlyBurden([active, dormant])).toBe(10);
    expect(annualBurden([active, dormant])).toBe(120);
    expect(possibleMonthlyBurden([active, dormant])).toBe(20);
  });
});
