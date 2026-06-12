import {
  LayoutDashboard,
  Wallet,
  ArrowLeftRight,
  Target,
  PieChart,
  Repeat,
  TrendingUp,
  Settings,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** The form / folio number engraved beside the entry in the index. */
  folio: string;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard, folio: "I" },
  { to: "/accounts", label: "Accounts", icon: Wallet, folio: "II" },
  { to: "/transactions", label: "Ledger", icon: ArrowLeftRight, folio: "III" },
  { to: "/budgets", label: "Budgets", icon: PieChart, folio: "IV" },
  { to: "/goals", label: "Goals", icon: Target, folio: "V" },
  { to: "/forecast", label: "Forecast", icon: TrendingUp, folio: "VI" },
  { to: "/subscriptions", label: "Standing Orders", icon: Repeat, folio: "VII" },
  { to: "/settings", label: "Settings", icon: Settings, folio: "VIII" },
];

/** A readable page title for the header, keyed by pathname. */
export function titleForPath(pathname: string): string {
  const exact = NAV_ITEMS.find((i) => i.to === pathname);
  if (exact) return exact.label;
  if (pathname.startsWith("/connect-bank")) return "Connect a Bank";
  return "The Ledger";
}
