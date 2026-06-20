/**
 * Forward-cadence helpers for the standing-orders timeline. Groups the
 * already-fetched `projectedTransactions` (GET /recurring/projected) into a
 * month-by-month agenda. Pure + testable; money is dollars at the boundary.
 */
import type { ProjectedTransaction } from "../store/store";

export interface CadenceMonth {
  key: string; // "YYYY-MM"
  label: string; // "July 2026"
  rows: ProjectedTransaction[];
  subtotal: number;
}

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** Group projected charges into chronological months, each with a subtotal. */
export function groupByMonth(rows: ProjectedTransaction[]): CadenceMonth[] {
  const byKey = new Map<string, ProjectedTransaction[]>();
  for (const r of rows) {
    const key = (r.date || "").slice(0, 7); // "YYYY-MM"
    if (key.length !== 7) continue;
    const list = byKey.get(key);
    if (list) list.push(r);
    else byKey.set(key, [r]);
  }
  return [...byKey.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, list]) => {
      const [year, month] = key.split("-");
      const label = `${MONTH_NAMES[Number(month) - 1]} ${year}`;
      const sorted = [...list].sort((a, b) => a.date.localeCompare(b.date));
      const subtotal = list.reduce((sum, r) => sum + r.amount, 0);
      return { key, label, rows: sorted, subtotal };
    });
}

/** Grand total of every projected charge in the window. */
export function next90Total(rows: ProjectedTransaction[]): number {
  return rows.reduce((sum, r) => sum + r.amount, 0);
}
