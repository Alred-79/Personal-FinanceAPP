/**
 * The notice registry — one source of truth for how each notification kind is
 * rendered (engraved icon + ink), where it deep-links, its call-to-action verb,
 * and its severity/group for the Auditor's Report. Shared by the bell and the
 * report so the two never drift.
 *
 * `tone` stays inside the colour law: debit-red for money-out warnings, gold for
 * an attention nudge, neutral otherwise — never the amber `--game-accent`.
 */
import {
  AlertTriangle,
  TrendingUp,
  FileText,
  Store,
  Waves,
  Target,
  Coins,
  ScrollText,
  MapPin,
  type LucideIcon,
} from "lucide-react";

export type NoticeTone = "debit" | "gold" | "muted";

export interface NoticeMeta {
  icon: LucideIcon;
  tone: NoticeTone;
  /** Deep-link destination. Omitted for proposal types (handled inline). */
  to?: string;
  verb?: string;
}

export const NOTICE: Record<string, NoticeMeta> = {
  budget_overrun: { icon: AlertTriangle, tone: "debit", to: "/budgets", verb: "Review budget" },
  anomaly: { icon: TrendingUp, tone: "gold", to: "/transactions", verb: "Inspect ledger" },
  merchant_lifecycle: { icon: Store, tone: "gold", to: "/subscriptions", verb: "Review subscription" },
  price_creep: { icon: TrendingUp, tone: "debit", to: "/subscriptions", verb: "Check price" },
  overdraft_risk: { icon: Waves, tone: "debit", to: "/forecast", verb: "View forecast" },
  plan_drift: { icon: TrendingUp, tone: "gold", to: "/forecast", verb: "Review plan" },
  audit_digest: { icon: FileText, tone: "gold", to: "/", verb: "Review findings" },
  goal_reminder: { icon: Target, tone: "gold", to: "/goals", verb: "Review goal" },
  // proposal types: no `to` — the one-tap Approve renders inline.
  rule_proposal: { icon: Coins, tone: "gold", verb: "Approve set-aside" },
  rule_suggest: { icon: ScrollText, tone: "gold", to: "/rules", verb: "Make it a rule" },
  landmark_reentry: { icon: MapPin, tone: "muted", to: "/", verb: "Revisit" },
};

export const FALLBACK: NoticeMeta = { icon: FileText, tone: "muted" };

export const TONE_TEXT: Record<NoticeTone, string> = {
  debit: "text-debit",
  gold: "text-gold",
  muted: "text-muted-foreground",
};

export const TONE_EDGE: Record<NoticeTone, string> = {
  debit: "border-l-debit/70",
  gold: "border-l-gold/70",
  muted: "border-l-transparent",
};

export const metaFor = (type: string): NoticeMeta => NOTICE[type] ?? FALLBACK;

/** A notice that mints a one-tap confirm token rather than navigating. */
export const isProposal = (type: string): boolean =>
  type === "rule_proposal" || type === "rule_suggest";

export type Severity = "alert" | "warn" | "info";

const ALERT = new Set(["overdraft_risk", "budget_overrun", "price_creep"]);
const WARN = new Set([
  "plan_drift",
  "merchant_lifecycle",
  "anomaly",
  "rule_proposal",
  "rule_suggest",
  "goal_reminder",
]);

export function severityFor(type: string): Severity {
  if (ALERT.has(type)) return "alert";
  if (WARN.has(type)) return "warn";
  return "info";
}

/** The Auditor's Report section a finding belongs to. */
export const NOTICE_GROUPS = [
  "Risk & Drift",
  "Budgets",
  "Merchants",
  "Proposals",
  "Other",
] as const;
export type NoticeGroup = (typeof NOTICE_GROUPS)[number];

export function groupFor(type: string): NoticeGroup {
  switch (type) {
    case "overdraft_risk":
    case "plan_drift":
      return "Risk & Drift";
    case "budget_overrun":
      return "Budgets";
    case "merchant_lifecycle":
    case "price_creep":
      return "Merchants";
    case "rule_proposal":
    case "rule_suggest":
    case "goal_reminder":
      return "Proposals";
    default:
      return "Other";
  }
}

/** Compact "2h ago" / "3d ago" / "Jun 14" stamp from an ISO string. */
export function relTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const s = (Date.now() - then) / 1000;
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86_400) return `${Math.round(s / 3600)}h ago`;
  if (s < 604_800) return `${Math.round(s / 86_400)}d ago`;
  return new Date(then).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}
