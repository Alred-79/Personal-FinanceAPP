import { NavLink } from "react-router-dom";
import { Building2, LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { NAV_ITEMS } from "./nav";
import { useStore } from "@/store/store";

interface SidebarProps {
  /** Opens the Plaid Link flow; disabled until the handler is ready. */
  onConnectBank: () => void;
  canConnectBank: boolean;
  onLogout: () => void;
  /** Called after navigating, so the mobile drawer can close itself. */
  onNavigate?: () => void;
}

export default function Sidebar({
  onConnectBank,
  canConnectBank,
  onLogout,
  onNavigate,
}: SidebarProps) {
  const user = useStore((s) => s.user);

  return (
    <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
      {/* Brand */}
      <div className="flex h-16 items-center gap-2 border-b-2 border-white/15 px-6">
        <span className="grid h-8 w-8 place-items-center border-2 border-sidebar-foreground bg-primary text-primary-foreground font-display text-lg font-bold">
          F
        </span>
        <span className="font-display text-xl font-bold uppercase tracking-tight">
          Finance-Tracker
        </span>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-1 px-3 py-4">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 border-2 border-transparent px-3 py-2.5 text-sm font-bold uppercase tracking-wide transition-colors",
                "text-sidebar-foreground/70 hover:bg-white/5 hover:text-sidebar-foreground",
                isActive &&
                  "border-sidebar-foreground bg-secondary text-secondary-foreground hover:bg-secondary"
              )
            }
          >
            <Icon className="h-[18px] w-[18px] shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer: bank + user + logout */}
      <div className="space-y-1 border-t-2 border-white/15 p-3">
        <button
          onClick={onConnectBank}
          disabled={!canConnectBank}
          className="flex w-full items-center gap-3 border-2 border-transparent px-3 py-2.5 text-sm font-bold uppercase tracking-wide text-sidebar-foreground/70 transition-colors hover:bg-white/5 hover:text-sidebar-foreground disabled:opacity-50"
        >
          <Building2 className="h-[18px] w-[18px] shrink-0" />
          Connect Bank
        </button>

        <div className="flex items-center gap-3 px-3 py-2">
          <span className="grid h-8 w-8 shrink-0 place-items-center border-2 border-sidebar-foreground bg-secondary text-sm font-bold text-secondary-foreground">
            {(user?.full_name || user?.username || "?").charAt(0).toUpperCase()}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-bold">
              {user?.full_name || user?.username || "Account"}
            </p>
          </div>
          <button
            onClick={onLogout}
            aria-label="Log out"
            className="border-2 border-transparent p-1.5 text-sidebar-foreground/60 transition-colors hover:bg-white/5 hover:text-sidebar-foreground"
          >
            <LogOut className="h-[18px] w-[18px]" />
          </button>
        </div>
      </div>
    </div>
  );
}
