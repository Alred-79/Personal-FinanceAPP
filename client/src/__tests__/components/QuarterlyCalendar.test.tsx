import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// The wax Seal renders its own "Paid" SVG label; stub it so we count only the
// status label under each plate.
vi.mock("@/components/engraving/Seal", () => ({ Seal: () => null }));

import { QuarterlyCalendar } from "@/components/custom/Tax/QuarterlyCalendar";

// Only the fields QuarterlyCalendar reads need to be present.
const base = {
  safe_harbor_per_quarter: null,
  due_dates: [
    ["Q1", "2026-04-15"],
    ["Q2", "2026-06-15"],
    ["Q3", "2026-09-15"],
    ["Q4", "2027-01-15"],
  ],
} as unknown as Parameters<typeof QuarterlyCalendar>[0]["quarterly"];

describe("QuarterlyCalendar covered-quarter math (Bug E)", () => {
  it("marks no quarters Paid when nothing has been paid", () => {
    // No payments: per_quarter is the full annual/4.
    render(
      <QuarterlyCalendar
        quarterly={{ ...base, per_quarter: 1108.675, payments_made: 0 }}
      />,
    );
    expect(screen.queryAllByText("Paid")).toHaveLength(0);
  });

  it("marks only the covered quarters Paid on a partial payment, not all four", () => {
    // Annual $4,434.70, paid $2,300 → backend reports per_quarter = remaining/4
    // = $533.67. The gross per-quarter is $1,108.67, so 2 quarters are covered.
    render(
      <QuarterlyCalendar
        quarterly={{ ...base, per_quarter: 533.675, payments_made: 2300 }}
      />,
    );
    expect(screen.queryAllByText("Paid")).toHaveLength(2);
  });
});
