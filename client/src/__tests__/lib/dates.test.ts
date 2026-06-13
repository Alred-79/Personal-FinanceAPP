import { describe, it, expect } from "vitest";
import {
  currentWeekRange,
  toLocalISODate,
  parseLocalISODate,
  todayLocalISO,
} from "@/lib/dates";

// These helpers must stay in the LOCAL calendar (no UTC round-trip). The tests
// below are timezone-agnostic in their assertions: they read back the same
// local Y/M/D that went in, which is exactly the property that breaks when a
// helper detours through toISOString()/UTC. The suite is run under multiple TZs
// (see `test:dates:zones` in package.json) to prove no offset shift.

describe("toLocalISODate", () => {
  it("serializes a local Date to its local calendar date (no UTC shift)", () => {
    // June 12 2026, local midnight. In a positive-offset zone toISOString()
    // would roll this back to June 11; toLocalISODate must keep June 12.
    expect(toLocalISODate(new Date(2026, 5, 12))).toBe("2026-06-12");
  });

  it("keeps the local day for a late-evening time (negative-offset trap)", () => {
    // 23:30 local on Jan 31. In a negative-offset zone toISOString() rolls this
    // to Feb 1 (UTC); the local helper must report Jan 31.
    expect(toLocalISODate(new Date(2026, 0, 31, 23, 30))).toBe("2026-01-31");
  });

  it("keeps the local day for an early-morning time (positive-offset trap)", () => {
    // 00:30 local on Mar 1. In a positive-offset zone toISOString() rolls this
    // back to Feb 28/29 (UTC); the local helper must report Mar 1.
    expect(toLocalISODate(new Date(2026, 2, 1, 0, 30))).toBe("2026-03-01");
  });

  it("zero-pads single-digit month and day", () => {
    expect(toLocalISODate(new Date(2026, 0, 5))).toBe("2026-01-05");
  });
});

describe("parseLocalISODate", () => {
  it("parses YYYY-MM-DD to LOCAL midnight (getDate matches the input day)", () => {
    const d = parseLocalISODate("2026-06-12");
    expect(d.getFullYear()).toBe(2026);
    expect(d.getMonth()).toBe(5); // June (0-indexed)
    expect(d.getDate()).toBe(12); // would be 11 if parsed as UTC midnight
  });

  it("round-trips with toLocalISODate", () => {
    expect(toLocalISODate(parseLocalISODate("2026-12-31"))).toBe("2026-12-31");
    expect(toLocalISODate(parseLocalISODate("2026-01-01"))).toBe("2026-01-01");
  });
});

describe("todayLocalISO", () => {
  it("returns today's local calendar date as YYYY-MM-DD", () => {
    const now = new Date();
    const expected = `${now.getFullYear()}-${`${now.getMonth() + 1}`.padStart(
      2,
      "0"
    )}-${`${now.getDate()}`.padStart(2, "0")}`;
    expect(todayLocalISO()).toBe(expected);
  });
});

describe("currentWeekRange", () => {
  it("returns an object with startDate and endDate", () => {
    const result = currentWeekRange();
    expect(result).toHaveProperty("startDate");
    expect(result).toHaveProperty("endDate");
  });

  it("startDate is a valid ISO date string", () => {
    const { startDate } = currentWeekRange();
    expect(startDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("endDate is a valid ISO date string", () => {
    const { endDate } = currentWeekRange();
    expect(endDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("endDate is >= startDate", () => {
    const { startDate, endDate } = currentWeekRange();
    expect(endDate >= startDate).toBe(true);
  });

  it("range spans exactly 6 days (Sunday to Saturday)", () => {
    const { startDate, endDate } = currentWeekRange();
    // Parse as LOCAL dates so the span is measured in local calendar days,
    // not shifted by the runner's timezone.
    const diff =
      (parseLocalISODate(endDate).getTime() -
        parseLocalISODate(startDate).getTime()) /
      (1000 * 60 * 60 * 24);
    expect(diff).toBe(6);
  });

  it("startDate is a local Sunday and endDate a local Saturday", () => {
    const { startDate, endDate } = currentWeekRange();
    // Boundaries are derived from the LOCAL week, so a local parse must land on
    // Sunday (0) and Saturday (6).
    expect(parseLocalISODate(startDate).getDay()).toBe(0);
    expect(parseLocalISODate(endDate).getDay()).toBe(6);
  });

  it("week boundaries bracket today in the local calendar", () => {
    const { startDate, endDate } = currentWeekRange();
    const today = todayLocalISO();
    expect(startDate <= today).toBe(true);
    expect(today <= endDate).toBe(true);
  });
});
