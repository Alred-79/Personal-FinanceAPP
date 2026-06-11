import {
  LayoutDashboard,
  Wallet,
  ArrowLeftRight,
  Target,
  PieChart,
  Repeat,
  Settings,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/accounts", label: "Accounts", icon: Wallet },
  { to: "/transactions", label: "Transactions", icon: ArrowLeftRight },
  { to: "/budgets", label: "Budgets", icon: PieChart },
  { to: "/goals", label: "Goals", icon: Target },
  { to: "/subscriptions", label: "Subscriptions", icon: Repeat },
  { to: "/settings", label: "Settings", icon: Settings },
];

/** A readable page title for the header, keyed by pathname. */
export function titleForPath(pathname: string): string {
  const exact = NAV_ITEMS.find((i) => i.to === pathname);
  if (exact) return exact.label;
  if (pathname.startsWith("/connect-bank")) return "Connect a Bank";
  return "Finance-Tracker";
}
