import {
  LayoutDashboard,
  Wallet,
  ArrowLeftRight,
  Target,
  PieChart,
  Repeat,
  TrendingUp,
  FileUp,
  Settings,
  Shield,
  Swords,
  Map,
  type LucideIcon,
} from "lucide-react";

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
  /** When true, this entry only appears in nav when the game layer is on
   * (ambient/full). The ROUTE always exists; this flags its nav PRESENCE. */
  gameOnly?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Overview", termKey: "nav.overview", icon: LayoutDashboard, folio: "I" },
  { to: "/accounts", label: "Accounts", termKey: "nav.accounts", icon: Wallet, folio: "II" },
  { to: "/transactions", label: "Ledger", termKey: "nav.transactions", icon: ArrowLeftRight, folio: "III" },
  { to: "/budgets", label: "Budgets", termKey: "nav.budgets", icon: PieChart, folio: "IV" },
  { to: "/goals", label: "Goals", termKey: "nav.goals", icon: Target, folio: "V" },
  { to: "/forecast", label: "Forecast", termKey: "nav.forecast", icon: TrendingUp, folio: "VI" },
  { to: "/subscriptions", label: "Standing Orders", termKey: "nav.subscriptions", icon: Repeat, folio: "VII" },
  { to: "/reconcile", label: "Reconciliation Desk", termKey: "nav.reconcile", icon: FileUp, folio: "XII" },
  { to: "/keeper", label: "Profile & Progress", termKey: "nav.keeper", icon: Shield, folio: "IX", gameOnly: true },
  { to: "/debts", label: "Debts", termKey: "nav.debts", icon: Swords, folio: "X", gameOnly: true },
  { to: "/campaigns", label: "Quarterly Review", termKey: "nav.campaigns", icon: Map, folio: "XI", gameOnly: true },
  { to: "/settings", label: "Settings", termKey: "nav.settings", icon: Settings, folio: "VIII" },
];

/** A readable page title for the header, keyed by pathname. */
export function titleForPath(pathname: string): string {
  const exact = NAV_ITEMS.find((i) => i.to === pathname);
  if (exact) return exact.label;
  if (pathname.startsWith("/connect-bank")) return "Connect a Bank";
  return "The Ledger";
}
