/**
 * Standing-orders math, extracted from the Subscriptions page so the card, the
 * burden headers, and the at-risk grouping share one source of truth.
 *
 * All amounts are dollars at the boundary (the backend speaks cents). Cadence
 * multipliers mirror the detector's windows in subscription_service.py.
 */
import { Subscription } from "../types";

/** Dollars this mandate costs per month, normalised across cadences. */
export function perMonth(amount: number, cadence: string): number {
  switch (cadence) {
    case "weekly":
      return amount * 4.33;
    case "bi-weekly":
      return amount * 2.17;
    case "quarterly":
      return amount / 3;
    case "annually":
      return amount / 12;
    default: // monthly
      return amount;
  }
}

/** Dollars per year (monthly × 12, so the two figures always agree). */
export function perYear(amount: number, cadence: string): number {
  return perMonth(amount, cadence) * 12;
}

/** Project the latest observed charge forward; amount already includes any rise. */
export function projectedAnnual(sub: Subscription): number {
  return perYear(sub.amount, sub.cadence);
}

/**
 * A mandate is "at risk" when the lifecycle model thinks it may have lapsed —
 * a coarse status of lapsing/dormant OR a probability_alive below half. Used to
 * group the calmer "at risk" section; absent lifecycle data → never at risk.
 */
export function isAtRisk(sub: Subscription): boolean {
  if (sub.lifecycle_status === "lapsing" || sub.lifecycle_status === "dormant") {
    return true;
  }
  return sub.probability_alive != null && sub.probability_alive < 0.5;
}

/** True when ANY subscription carries lifecycle enrichment (flag is on). */
export function hasLifecycleData(subs: Subscription[]): boolean {
  return subs.some(
    (s) => s.probability_alive != null || s.lifecycle_status != null
  );
}

export const monthlyBurden = (subs: Subscription[]): number =>
  subs
    .filter((s) => !hasLifecycleData(subs) || !isAtRisk(s))
    .reduce((sum, s) => sum + perMonth(s.amount, s.cadence), 0);

export const annualBurden = (subs: Subscription[]): number =>
  subs
    .filter((s) => !hasLifecycleData(subs) || !isAtRisk(s))
    .reduce((sum, s) => sum + projectedAnnual(s), 0);

export const possibleMonthlyBurden = (subs: Subscription[]): number =>
  subs.filter(isAtRisk).reduce((sum, s) => sum + perMonth(s.amount, s.cadence), 0);
