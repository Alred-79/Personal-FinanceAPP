import { describe, it, expect } from "vitest";
import { currentWeekRange } from "@/lib/dates";

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
    const diff =
      (new Date(endDate).getTime() - new Date(startDate).getTime()) /
      (1000 * 60 * 60 * 24);
    expect(diff).toBe(6);
  });

  it("startDate is a Sunday (day index 0)", () => {
    const { startDate } = currentWeekRange();
    // Add 'T12:00:00' to avoid UTC offset edge cases
    const day = new Date(`${startDate}T12:00:00`).getDay();
    expect(day).toBe(0);
  });

  it("endDate is a Saturday (day index 6)", () => {
    const { endDate } = currentWeekRange();
    const day = new Date(`${endDate}T12:00:00`).getDay();
    expect(day).toBe(6);
  });
});
