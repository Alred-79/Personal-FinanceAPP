/**
 * The Mint Floor — game-section tuning constants (THE single tuning surface).
 *
 * HONESTY LAW (docs/GAME-MODE-MINTFLOOR-PLAN.md): every number here is a real
 * backend mechanic's real value, traceable to server/src/services/game/boss.py
 * and the seeded Sapphire Credit Card liability (server/scripts/seed_demo.py).
 * No invented stats. The phosphor/amber accent is CHROME only — money/HP figures
 * keep the credit/debit/gold color law (.figure strips all glow/scanline filters).
 *
 *   Seed liability (seed_demo.py seed_liabilities):
 *     Sapphire Credit Card — principal_cents=84_213 ($842.13),
 *     apr_bps=2399, minimum_payment_cents=3_500 ($35.00).
 *   boss.py: damage = raw payment amount (hp' = max(hp - amount, 0));
 *     CRIT = minimum>0 AND amount > minimum × CRIT_MULTIPLE (1.25);
 *     PHASE_FRACTION 0.20 (5 bands); APR heal = round(principal × apr_bps/120000).
 */

// ─────────────────────────────────────────────────────────────────────────────
// Money helpers
// ─────────────────────────────────────────────────────────────────────────────

/** integer cents → "$1,234" (whole-dollar HP read). */
export function dollars(cents: number): string {
  return `$${Math.round(cents / 100).toLocaleString("en-US")}`;
}
/** integer cents → "$1,234.56" (payment chunks, serial). */
export function dollarsCents(cents: number): string {
  return `$${(cents / 100).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Boss — the real seeded Sapphire Credit Card (boss.py mechanics)
// ─────────────────────────────────────────────────────────────────────────────

export const BOSS = {
  /** Real seed liability name. */
  name: "Sapphire Credit Card",
  /** Starting HP = principal_cents. $842.13 — the REAL seeded balance. */
  startCents: 84_213,
  /** minimum_payment_cents = $35.00 (seed). */
  minPaymentCents: 3_500,
  /** apr_bps = 2399 → 23.99% APR (seed). */
  aprBps: 2399,
  /** boss.py CRIT_MULTIPLE — CRIT when amount > minimum × 1.25. NEVER multiplies damage. */
  critMultiple: 1.25,
  /** boss.py PHASE_FRACTION — a phase breaks at each 20% of starting HP (5 bands). */
  phaseFraction: 0.2,
  phases: 5,
} as const;

/** HP serial init, cents. */
export const HP_START_CENTS = BOSS.startCents; // 84_213
/** Real statement minimum, cents. The tap/quick-strike floor. */
export const MIN_CENTS = BOSS.minPaymentCents; // 3_500 ($35.00)
/**
 * Top of the dial — a real, allowed payment for an $842 card. Holding to max
 * pays $120 in one strike (well under the full balance; never inflated).
 */
export const MAX_STRIKE = 12_000; // $120.00

/** boss.py CRIT_MULTIPLE. */
export const CRIT_MULTIPLE = BOSS.critMultiple; // 1.25
/**
 * CRIT threshold, cents. boss.py: crit = minimum>0 AND amount > minimum×1.25.
 * 3_500 × 1.25 = 4_375 → CRIT fires when payment > $43.75. A real, player-
 * crossable threshold; it flips juice + faster HEAT only, never damage.
 */
export const CRIT_THRESHOLD_CENTS = Math.round(MIN_CENTS * CRIT_MULTIPLE); // 4_375

// ─────────────────────────────────────────────────────────────────────────────
// Charge → magnitude → CRIT mapping (motionSpec, rebalanced from binary-CRIT)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * A press released within this window is a TAP → a clean, intentional
 * sub-CRIT "quick strike" of exactly MIN_CENTS ($35), with NO charge ramp
 * consulted. Guarantees an instant tap is never an accidental CRIT, on both
 * pointer and keyboard. The rAF charge clock only starts AFTER this window.
 */
export const TAP_MAX_MS = 140;

/** Hold time (after the tap window) to reach full charge (charge=1 → MAX_STRIKE). */
export const CHARGE_TO_MAX_MS = 1600;

/** easeInOutCubic — gentle start so the dollar figure does not leap past CRIT,
 *  then accelerates. The opposite of the old fast-early curve that made CRIT binary. */
export function easeInOutCubic(c: number): number {
  const x = Math.min(1, Math.max(0, c));
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
}

/** charge (0..1) → payment cents (rounded), via easeInOutCubic over [MIN, MAX]. */
export function chargeToPaymentCents(charge: number): number {
  const t = easeInOutCubic(charge);
  return Math.round(MIN_CENTS + (MAX_STRIKE - MIN_CENTS) * t);
}

/**
 * The charge fraction at which payment first exceeds CRIT_THRESHOLD.
 * Solved numerically (NOT hand-waved): easeInOutCubic(charge) must reach
 * (CRIT_THRESHOLD - MIN)/(MAX - MIN) ≈ 0.1029 → charge ≈ 0.29. Used to place
 * the fixed CRIT-line marker on the gauge.
 */
export const CRIT_CHARGE_FRACTION = ((): number => {
  const target = (CRIT_THRESHOLD_CENTS - MIN_CENTS) / (MAX_STRIKE - MIN_CENTS);
  // binary-search the monotone easeInOutCubic
  let lo = 0;
  let hi = 1;
  for (let i = 0; i < 40; i++) {
    const mid = (lo + hi) / 2;
    if (easeInOutCubic(mid) < target) lo = mid;
    else hi = mid;
  }
  return (lo + hi) / 2;
})();

// ─────────────────────────────────────────────────────────────────────────────
// Combo / HEAT (the decaying in-session streak — the honest loss condition)
// ─────────────────────────────────────────────────────────────────────────────

/** The "beat". A strike released within this of the prior release → combo++. */
export const COMBO_WINDOW_MS = 1100;
/** After idle past the beat, cool one HEAT tier every this many ms. */
export const HEAT_DECAY_MS = 900;
/** boss.py-mirrored monthly heat cap (heat.py MONTHLY_HEAT_CAP). */
export const HEAT_CAP = 6;
/**
 * heatProgress thresholds → heatTier 1..6 (escalating spacing so later tiers
 * are earned). heatProgress is a SEPARATE accumulator: +1 per on-beat strike,
 * +2 on CRIT. combo stays a pure integer; only heatProgress feels CRIT's +2.
 */
export const TIER_BOUNDARIES = [1, 2, 3, 5, 7, 10] as const;

/** heatProgress → tier (0..6). */
export function tierForProgress(progress: number): number {
  let tier = 0;
  for (let i = 0; i < TIER_BOUNDARIES.length; i++) {
    if (progress >= TIER_BOUNDARIES[i]) tier = i + 1;
  }
  return Math.min(tier, HEAT_CAP);
}

// ─────────────────────────────────────────────────────────────────────────────
// XP / level / prestige / APR — real backend formulas (xp.py / expedition.py)
// ─────────────────────────────────────────────────────────────────────────────

/** xp.py — a PaymentPosted earns +20. The dialed payment IS a real PaymentPosted. */
export const XP_PER_STRIKE = 20;
/** xp.py — level = floor(sqrt(xp / LEVEL_K)). */
export const LEVEL_K = 120;
export function xpLevel(xp: number): number {
  return Math.floor(Math.sqrt(xp / LEVEL_K));
}
export function xpForLevel(level: number): number {
  return level * level * LEVEL_K;
}

/** expedition.py — prestige = floor(PRESTIGE_K × sqrt(score)), score in [0,1]. */
export const PRESTIGE_K = 10;
export function prestigeForScore(score: number): number {
  return Math.floor(PRESTIGE_K * Math.sqrt(Math.min(1, Math.max(0, score))));
}

/** boss.py monthly_apr_interest_cents = round(principal × apr_bps/10000/12). */
export const APR_BPS = BOSS.aprBps; // 2399
export function aprHeal(principalCents: number): number {
  return Math.round((principalCents * APR_BPS) / 10_000 / 12);
}

/**
 * Amortize the seeded card at a fixed monthly payment, the balance HEALING by
 * real APR interest each month (the in-app boss mechanic, projected forward).
 * Returns months to clear and total interest paid. A payment at or below the
 * first month's interest never clears (guarded → Infinity); the Debt Boss
 * slider floor is the real $35 statement minimum, which always clears.
 */
export function simulatePayoff(
  paymentCents: number,
  startCents: number = HP_START_CENTS,
): { months: number; interestCents: number; paidOff: boolean } {
  let bal = startCents;
  if (paymentCents <= aprHeal(bal)) {
    return { months: Infinity, interestCents: Infinity, paidOff: false };
  }
  let interest = 0;
  let months = 0;
  while (bal > 0 && months < 1200) {
    const heal = aprHeal(bal);
    interest += heal;
    bal = Math.max(0, bal + heal - paymentCents);
    months += 1;
  }
  return { months, interestCents: interest, paidOff: bal <= 0 };
}

// ─────────────────────────────────────────────────────────────────────────────
// Phase band math (boss.py _phase_indices_crossed)
// ─────────────────────────────────────────────────────────────────────────────

export const PHASE_FRACTION = BOSS.phaseFraction; // 0.20

/** number of 20% bands cleared at a given hp (boss.py `cleared`). */
export function bandsCleared(startingHp: number, hp: number): number {
  if (startingHp <= 0) return 0;
  const band = startingHp * PHASE_FRACTION;
  return Math.floor((startingHp - hp) / band);
}

/** NEW phase indices (1..5) crossed moving hp_before → hp_after (boss.py). */
export function phaseIndicesCrossed(
  startingHp: number,
  hpBefore: number,
  hpAfter: number,
): number[] {
  const before = bandsCleared(startingHp, hpBefore);
  const after = bandsCleared(startingHp, hpAfter);
  const out: number[] = [];
  for (let i = before + 1; i <= after; i++) if (i >= 1 && i <= 5) out.push(i);
  return out;
}

// ─────────────────────────────────────────────────────────────────────────────
// Juice allowlist — celebrations fire ONLY for these (boss.py JUICE_EVENTS)
// ─────────────────────────────────────────────────────────────────────────────

export const JUICE_EVENTS = new Set<string>([
  "BossDamagedCrit", // only the crit variant, never plain BossDamaged
  "BossPhaseBroken",
  "BossDefeated",
  "BossSealed",
  "GoalFunded",
  "RuleExecutedSweep",
  "LevelUp",
]);

// ─────────────────────────────────────────────────────────────────────────────
// localStorage best-run (namespaced + versioned)
// ─────────────────────────────────────────────────────────────────────────────

export const LS_KEY = "theledger.mintfloor.bestrun.v1";
export const LS_VERSION = 1;

// ─────────────────────────────────────────────────────────────────────────────
// Mode
// ─────────────────────────────────────────────────────────────────────────────

export type Intensity = "off" | "ambient" | "full";

// ─────────────────────────────────────────────────────────────────────────────
// Expedition rank garnish (returning-visit only; not the primary in-session hook)
// ─────────────────────────────────────────────────────────────────────────────

/** rank seal E→S from a prestige value (returning-visit garnish). */
export function rankForPrestige(prestige: number): string {
  if (prestige >= 9) return "S";
  if (prestige >= 7) return "A";
  if (prestige >= 5) return "B";
  if (prestige >= 3) return "C";
  if (prestige >= 1) return "D";
  return "E";
}
