/**
 * Local-date helpers.
 *
 * Finance dates are *calendar* dates, not instants. Serializing a local Date
 * with `toISOString()` converts to UTC first, so a transaction the user enters
 * at, say, 8pm in UTC-5 ("today") would serialize to *tomorrow* in UTC — an
 * off-by-one that puts the entry on the wrong day. Parsing `new Date("YYYY-MM-DD")`
 * has the mirror bug: it's interpreted as UTC midnight, which is the *previous*
 * day for negative-offset zones once rendered in local time.
 *
 * These helpers stay entirely in the local calendar: no UTC round-trip. Route
 * every "what day is this" site through them.
 */

/** Serialize a Date to its LOCAL calendar date as `YYYY-MM-DD` (no UTC shift). */
export const toLocalISODate = (d: Date): string => {
  const y = d.getFullYear();
  const m = `${d.getMonth() + 1}`.padStart(2, "0");
  const day = `${d.getDate()}`.padStart(2, "0");
  return `${y}-${m}-${day}`;
};

/** Parse a `YYYY-MM-DD` string into a LOCAL-midnight Date (not UTC midnight). */
export const parseLocalISODate = (s: string): Date => {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
};

/** Today's LOCAL calendar date as `YYYY-MM-DD`. */
export const todayLocalISO = () => toLocalISODate(new Date());

/** Returns the ISO YYYY-MM-DD start and end of the current week, Sunday to Saturday. */
export function currentWeekRange(): { startDate: string; endDate: string } {
  const today = new Date();
  const start = new Date(today);
  start.setDate(today.getDate() - today.getDay());
  const end = new Date(today);
  end.setDate(today.getDate() + (6 - today.getDay()));
  return {
    startDate: toLocalISODate(start),
    endDate: toLocalISODate(end),
  };
}
