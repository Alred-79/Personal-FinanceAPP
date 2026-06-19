import {
  LayoutDashboard,
  Wallet,
  ArrowLeftRight,
  Target,
  PieChart,
  Repeat,
  TrendingUp,
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
export type NavGroup = "ledger" | "tools" | "game";

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
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Overview", termKey: "nav.overview", icon: LayoutDashboard, folio: "I", group: "ledger" },
  { to: "/accounts", label: "Accounts", termKey: "nav.accounts", icon: Wallet, folio: "II", group: "ledger" },
  { to: "/transactions", label: "Ledger", termKey: "nav.transactions", icon: ArrowLeftRight, folio: "III", group: "ledger" },
  { to: "/budgets", label: "Budgets", termKey: "nav.budgets", icon: PieChart, folio: "IV", group: "ledger" },
  { to: "/goals", label: "Goals", termKey: "nav.goals", icon: Target, folio: "V", group: "ledger" },
  { to: "/forecast", label: "Forecast", termKey: "nav.forecast", icon: TrendingUp, folio: "VI", group: "ledger" },
  { to: "/subscriptions", label: "Standing Orders", termKey: "nav.subscriptions", icon: Repeat, folio: "VII", group: "tools" },
  { to: "/rules", label: "Rule Book", termKey: "nav.rules", icon: ScrollText, folio: "XIV", group: "tools" },
  { to: "/reconcile", label: "Reconciliation Desk", termKey: "nav.reconcile", icon: FileUp, folio: "XII", group: "tools" },
  { to: "/tax", label: "Tax Organizer", termKey: "nav.tax", icon: Receipt, folio: "XIII", taxOnly: true, group: "tools" },
  { to: "/keeper", label: "Profile & Progress", termKey: "nav.keeper", icon: Shield, folio: "IX", gameOnly: true, group: "game" },
  { to: "/debts", label: "Debts", termKey: "nav.debts", icon: Swords, folio: "X", gameOnly: true, group: "game" },
  { to: "/campaigns", label: "Quarterly Review", termKey: "nav.campaigns", icon: Map, folio: "XI", gameOnly: true, group: "game" },
  { to: "/settings", label: "Settings", termKey: "nav.settings", icon: Settings, folio: "VIII", group: "tools" },
];

/** Section order + headings for grouped nav surfaces. */
export const NAV_GROUPS: { key: NavGroup; label: string }[] = [
  { key: "ledger", label: "Ledger" },
  { key: "tools", label: "Tools" },
  { key: "game", label: "Game" },
];

/** A readable page title for the header, keyed by pathname. */
export function titleForPath(pathname: string): string {
  const exact = NAV_ITEMS.find((i) => i.to === pathname);
  if (exact) return exact.label;
  if (pathname.startsWith("/connect-bank")) return "Connect a Bank";
  return "The Ledger";
}
