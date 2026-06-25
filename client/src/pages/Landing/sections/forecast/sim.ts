/**
 * A compact, in-browser version of the product's real forecast engine — a
 * moving-block bootstrap over a scheduled cash-flow walk. It is faithful to the
 * server's method (server/src/services/forecast_sim.py): walk recurring bills +
 * income + a discretionary "burn", resample daily residuals in 7-day blocks to
 * preserve spending streaks, run many futures, then read percentile bands and an
 * overdraft probability off the simulated troughs. Seeded, so the band is stable
 * as you drag (it shifts smoothly, never jitters).
 */

export const DAYS = 30;
export const START = 2980; // starting balance, dollars

/** The scheduled net flow per day (recurring bills − / income +), in dollars. */
function baselineSchedule(): number[] {
  const net = new Array(DAYS).fill(0);
  const add = (d: number, amt: number) => {
    if (d >= 0 && d < DAYS) net[d] += amt;
  };
  add(4, -1300); // rent
  add(8, -200); // card
  add(12, -260); // utilities
  add(15, -180);
  add(18, 1900); // paycheck
  add(22, -150);
  add(26, -300); // insurance
  return net;
}

/** Daily discretionary residuals (deviations around the mean burn), dollars. */
const RAW_POOL = [-8, 22, -45, 12, -18, 40, -30, 6, -52, 28, -10, 34, -24, 16];
const POOL_MEAN = RAW_POOL.reduce((a, b) => a + b, 0) / RAW_POOL.length;
// centred on zero, scaled up so the band is clearly visible and the overdraft
// probability moves smoothly as you drag (rather than snapping 0→100%).
const POOL = RAW_POOL.map((r) => (r - POOL_MEAN) * 2.6);

export const BASE_BURN = 46; // dollars/day of discretionary spend at rest

/** Deterministic PRNG (mulberry32) so a given input yields a stable band. */
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function percentile(sorted: number[], p: number): number {
  const idx = (sorted.length - 1) * p;
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

export type SimResult = {
  prob: number; // overdraft probability, 0..1
  troughLow: number; // 5th pct of simulated troughs
  troughMed: number; // 50th
  troughHigh: number; // 95th
  ending: number; // median ending balance
  low: number[]; // per-day 5th pct balance
  med: number[]; // per-day median balance
  high: number[]; // per-day 95th pct balance
  troughDay: number; // index of the median's low point
};

export type SimOptions = {
  burn?: number;
  scenarioNet?: number[]; // extra net flows layered on the baseline (what-if)
  sims?: number;
  block?: number;
};

/** Run the bootstrap and return per-day bands + trough distribution. */
export function simulate(opts: SimOptions = {}): SimResult {
  const burn = opts.burn ?? BASE_BURN;
  const sims = opts.sims ?? 240;
  const block = opts.block ?? 7;
  const base = baselineSchedule();
  const net = opts.scenarioNet ? base.map((v, i) => v + (opts.scenarioNet![i] ?? 0)) : base;

  // band widens a little as spending climbs — more spend, more uncertainty
  const vol = 1 + Math.max(0, (burn - BASE_BURN)) / 90;
  const rand = mulberry32(1337);

  const byDay: number[][] = Array.from({ length: DAYS }, () => new Array(sims));
  const troughs = new Array(sims);

  for (let s = 0; s < sims; s++) {
    let bal = START;
    let mn = START;
    let blockStart = Math.floor(rand() * POOL.length);
    for (let d = 0; d < DAYS; d++) {
      if (d % block === 0) blockStart = Math.floor(rand() * POOL.length);
      const r = POOL[(blockStart + (d % block)) % POOL.length] * vol;
      bal += net[d] - burn + r;
      byDay[d][s] = bal;
      if (bal < mn) mn = bal;
    }
    troughs[s] = mn;
  }

  const low = new Array(DAYS);
  const med = new Array(DAYS);
  const high = new Array(DAYS);
  for (let d = 0; d < DAYS; d++) {
    const col = byDay[d].slice().sort((a, b) => a - b);
    low[d] = percentile(col, 0.05);
    med[d] = percentile(col, 0.5);
    high[d] = percentile(col, 0.95);
  }
  const sortedTr = troughs.slice().sort((a, b) => a - b);
  const overdrafts = troughs.reduce((n, t) => n + (t < 0 ? 1 : 0), 0);

  let troughDay = 0;
  for (let d = 1; d < DAYS; d++) if (med[d] < med[troughDay]) troughDay = d;

  return {
    prob: overdrafts / sims,
    troughLow: percentile(sortedTr, 0.05),
    troughMed: percentile(sortedTr, 0.5),
    troughHigh: percentile(sortedTr, 0.95),
    ending: med[DAYS - 1],
    low,
    med,
    high,
    troughDay,
  };
}

/** Catmull-Rom → cubic-bezier path through points, for a smooth coastline. */
export function smoothPath(pts: [number, number][]): string {
  if (pts.length < 2) return "";
  let d = `M ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] ?? p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C ${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d;
}
