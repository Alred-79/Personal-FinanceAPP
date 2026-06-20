/**
 * Pure helpers for the Almanac — net-worth trend stats and the spending
 * heat-grid pivot. No React, no I/O; unit-testable. Money is dollars.
 */
import type { AnalyticsSpending } from "../types";
import type { NetWorthPoint } from "../store/store";

const ms = (iso: string) => new Date(iso + "T00:00:00").getTime();

export interface NetWorthStats {
  current: number;
  athValue: number;
  athDate: string;
  delta30: number;
  delta90: number;
  delta365: number;
  /** Average change per month across the whole series (sign = direction). */
  perMonth: number;
}

/** The series value at (or just before) `days` ago, falling back to the first. */
function valueDaysAgo(points: NetWorthPoint[], days: number): number {
  if (points.length === 0) return 0;
  const cutoff = ms(points[points.length - 1].date) - days * 86_400_000;
  let chosen = points[0];
  for (const p of points) {
    if (ms(p.date) <= cutoff) chosen = p;
    else break; // ascending — past the cutoff
  }
  return chosen.total;
}

export function netWorthStats(points: NetWorthPoint[]): NetWorthStats | null {
  if (points.length === 0) return null;
  const current = points[points.length - 1].total;
  let ath = points[0];
  for (const p of points) if (p.total >= ath.total) ath = p;
  const first = points[0];
  const spanDays = Math.max(
    1,
    (ms(points[points.length - 1].date) - ms(first.date)) / 86_400_000
  );
  return {
    current,
    athValue: ath.total,
    athDate: ath.date,
    delta30: current - valueDaysAgo(points, 30),
    delta90: current - valueDaysAgo(points, 90),
    delta365: current - valueDaysAgo(points, 365),
    perMonth: ((current - first.total) / spanDays) * 30.4,
  };
}

export interface HeatGrid {
  /** Category rows, ordered by total spend desc (backend order). */
  categories: string[];
  /** Time-bucket columns, chronological. */
  buckets: string[];
  /** category → bucket → total dollars. */
  matrix: Record<string, Record<string, number>>;
  /** Per-column max, so a quiet category still reads (column-normalised alpha). */
  columnMax: Record<string, number>;
}

export function buildHeatGrid(a: AnalyticsSpending): HeatGrid {
  const buckets = Object.keys(a.totals_by_bucket).sort();
  const categories = Object.keys(a.totals_by_category);
  const matrix: Record<string, Record<string, number>> = {};
  for (const c of categories) matrix[c] = {};
  for (const cell of a.cells) {
    (matrix[cell.category] ??= {})[cell.bucket] = cell.total;
  }
  const columnMax: Record<string, number> = {};
  for (const b of buckets) {
    let m = 0;
    for (const c of categories) m = Math.max(m, matrix[c]?.[b] ?? 0);
    columnMax[b] = m || 1;
  }
  return { categories, buckets, matrix, columnMax };
}

const MONTH_ABBR = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/** Short axis label for a bucket key, by bucket granularity. */
export function bucketLabel(key: string, bucket: string): string {
  if (bucket === "month") {
    const [, m] = key.split("-");
    return MONTH_ABBR[Number(m) - 1] ?? key;
  }
  if (bucket === "week") {
    // "YYYY-W03" → "W03", or a trailing "-NN" → "WNN"
    const wk = key.split("-W")[1] ?? key.split("-").pop() ?? key;
    return `W${wk}`;
  }
  // day: "YYYY-MM-DD" → "D"
  return key.split("-").pop() ?? key;
}
