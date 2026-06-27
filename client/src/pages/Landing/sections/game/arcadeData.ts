/**
 * The Penny Arcade — data for the two insight-first demos.
 *
 * These are NOT arcade reflex toys. Each demo is the REAL in-app mechanic made
 * playable, so a visitor SEES the value instead of being asked to take it on
 * faith. Debt Boss is the seeded Sapphire Card ($842.13 / 23.99% APR, see
 * gameData.ts BOSS) shown as a payoff simulator where the boss "heals" by real
 * monthly interest. Subscription Watch is the real recurring-charge detector
 * with the +15% price-creep flag (server habit_monsters.py). Money figures keep
 * the credit/debit/gold .figure law.
 */

export type ArcadeGame = "boss" | "watch";

export const GAMES: { id: ArcadeGame; no: string; title: string; blurb: string }[] = [
  { id: "boss", no: "I", title: "The Debt Boss", blurb: "See what minimum payments really cost." },
  { id: "watch", no: "II", title: "Subscription Watch", blurb: "Find the charges quietly draining you." },
];

// ─────────────────────────────────────────────────────────────────────────────
// Subscription Watch — a sample of the recurring charges the detector surfaces
// ─────────────────────────────────────────────────────────────────────────────

/**
 * A tracked recurring charge. `prevCents` set ⇒ the price rose; a rise of
 * CREEP_THRESHOLD or more is flagged as price creep (habit_monsters.py).
 * `silent` ⇒ no recent use, the kind the app surfaces as a candidate to cut.
 */
export type Sub = {
  name: string;
  category: string;
  cents: number;
  prevCents?: number;
  silent?: boolean;
};

export const WATCH_SUBS: Sub[] = [
  { name: "Streamease", category: "video", cents: 1599, prevCents: 1299 }, // +23% creep
  { name: "AtlasGym", category: "fitness", cents: 4200, silent: true },
  { name: "CloudVault", category: "storage", cents: 999 },
  { name: "NewsDaily", category: "news", cents: 1200, silent: true },
  { name: "Soundwave+", category: "music", cents: 1299, prevCents: 1099 }, // +18% creep
  { name: "MealKit Co.", category: "food", cents: 7900 },
];

/** habit_monsters.py price-creep threshold — a +15% rise is flagged. */
export const CREEP_THRESHOLD = 0.15;

/** Fractional price rise if it clears the creep threshold, else null. */
export function creepPct(sub: Sub): number | null {
  if (!sub.prevCents || sub.prevCents <= 0) return null;
  const pct = (sub.cents - sub.prevCents) / sub.prevCents;
  return pct >= CREEP_THRESHOLD ? pct : null;
}
