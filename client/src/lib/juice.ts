/**
 * The juice allowlist (v4 §11, package 06).
 *
 * Celebrations fire ONLY for payoff events on this list — never for a purchase
 * (TxnPosted), a near-miss, or a streak event (those get the standard toast, not
 * juice). The allowlist-walk test is the structural enforcement; this is the one
 * place the set is defined so it can't drift.
 *
 * All animation is gated behind prefers-reduced-motion with a static fallback —
 * see `shouldAnimate()`.
 */

/** Payoff events that may trigger a celebration. Crit/sweep are variant-gated. */
export const JUICE_EVENTS = [
  "BossDamagedCrit",
  "BossPhaseBroken",
  "BossDefeated",
  "BossSealed",
  "GoalFunded",
  "RuleExecutedSweep",
  "LevelUp",
] as const;

export type JuiceEvent = (typeof JUICE_EVENTS)[number];

const JUICE_SET = new Set<string>(JUICE_EVENTS);

/**
 * Whether an event should celebrate. Plain BossDamaged only juices on a crit;
 * plain RuleExecuted only on the sweep kind — so a purchase or a routine
 * categorize never fires.
 */
export function isJuiceEvent(
  eventType: string,
  payload?: { crit?: boolean; kind?: string }
): boolean {
  if (eventType === "BossDamaged") return Boolean(payload?.crit);
  if (eventType === "RuleExecuted") return payload?.kind === "sweep";
  return JUICE_SET.has(eventType);
}

/** Respect prefers-reduced-motion: animations only when motion is allowed. */
export function shouldAnimate(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
