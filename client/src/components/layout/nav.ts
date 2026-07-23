import {
  LayoutDashboard,
  Wallet,
  ArrowLeftRight,
  Target,
  PieChart,
  Repeat,
  TrendingUp,
  BookOpen,
  Activity,
  FileUp,
  Receipt,
  Settings,
  Shield,
  Swords,
  Map,
  ScrollText,
  type LucideIcon,
} from "lucide-react";

/** Which section of the index an entry belongs to — drives grouped nav
 * surfaces (the Tools overflow, the sidebar rail sections, the ⌘K palette). */
export type NavGroup = "primary" | "plan" | "review" | "more";

export interface NavItem {
  to: string;
  /** The off-mode label (today's literal). Also the fallback if a term key is
   * missing, and the source for `titleForPath`. */
  label: string;
  /** The term-catalog key, so the visible label routes through `<Term/>`. */
  termKey: string;
  icon: LucideIcon;
  /** The form / folio number engraved beside the entry in the index. */
  folio: string;
  /** Section grouping (default "ledger"). */
  group: NavGroup;
  /** When true, this entry only appears in nav when the game layer is on
   * (ambient/full). The ROUTE always exists; this flags its nav PRESENCE. */
  gameOnly?: boolean;
  /** When true, this entry only appears in nav when the server's tax feature
   * flag is on. The ROUTE always exists (and self-handles the disabled state);
   * this flags its nav PRESENCE. */
  taxOnly?: boolean;
  /** When true, this entry only appears in nav when the server's freelancer
   * mode flag is on (W5). The ROUTE always exists; this flags nav PRESENCE. */
  freelancerOnly?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Overview", termKey: "nav.overview", icon: LayoutDashboard, folio: "I", group: "primary" },
  { to: "/forecast", label: "Decisions", termKey: "nav.forecast", icon: TrendingUp, folio: "VI", group: "primary" },
  { to: "/subscriptions", label: "Upcoming", termKey: "nav.subscriptions", icon: Repeat, folio: "VII", group: "primary" },
  { to: "/transactions", label: "Transactions", termKey: "nav.transactions", icon: ArrowLeftRight, folio: "III", group: "primary" },
  { to: "/accounts", label: "Accounts", termKey: "nav.accounts", icon: Wallet, folio: "II", group: "plan" },
  { to: "/budgets", label: "Budgets", termKey: "nav.budgets", icon: PieChart, folio: "IV", group: "plan" },
  { to: "/goals", label: "Goals", termKey: "nav.goals", icon: Target, folio: "V", group: "plan" },
  { to: "/income", label: "Income", termKey: "nav.income", icon: Activity, folio: "XVI", freelancerOnly: true, group: "plan" },
  { to: "/tax", label: "Tax Organizer", termKey: "nav.tax", icon: Receipt, folio: "XIII", taxOnly: true, group: "plan" },
  { to: "/almanac", label: "Insights", termKey: "nav.almanac", icon: BookOpen, folio: "XV", group: "review" },
  { to: "/reconcile", label: "Import & reconcile", termKey: "nav.reconcile", icon: FileUp, folio: "XII", group: "review" },
  { to: "/rules", label: "Rule Book", termKey: "nav.rules", icon: ScrollText, folio: "XIV", group: "review" },
  { to: "/keeper", label: "Profile & Progress", termKey: "nav.keeper", icon: Shield, folio: "IX", gameOnly: true, group: "more" },
  { to: "/debts", label: "Debts", termKey: "nav.debts", icon: Swords, folio: "X", gameOnly: true, group: "more" },
  { to: "/campaigns", label: "Quarterly Review", termKey: "nav.campaigns", icon: Map, folio: "XI", gameOnly: true, group: "more" },
  { to: "/settings", label: "Settings", termKey: "nav.settings", icon: Settings, folio: "VIII", group: "more" },
];

/** Section order + headings for grouped nav surfaces. */
export const NAV_GROUPS: { key: NavGroup; label: string }[] = [
  { key: "primary", label: "Daily" },
  { key: "plan", label: "Plan" },
  { key: "review", label: "Review" },
  { key: "more", label: "More" },
];

/** A readable page title for the header, keyed by pathname. */
export function titleForPath(pathname: string): string {
  const exact = NAV_ITEMS.find((i) => i.to === pathname);
  if (exact) return exact.label;
  if (pathname.startsWith("/connect-bank")) return "Connect a Bank";
  return "The Ledger";
}
