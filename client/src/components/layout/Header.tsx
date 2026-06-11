import { useState } from "react";
import { NavLink } from "react-router-dom";
import { Building2, LogOut, Menu, Moon, Sun } from "lucide-react";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import NotificationBell from "@/components/custom/NotificationBell/NotificationBell";
import { useTheme } from "@/hooks/theme";
import { useStore } from "@/store/store";
import { cn } from "@/lib/utils";
import { NAV_ITEMS } from "./nav";
import Sidebar from "./Sidebar";

interface HeaderProps {
  /** Page title (kept for API compatibility; rendered via PageHeader now). */
  title: string;
  onConnectBank: () => void;
  canConnectBank: boolean;
  onLogout: () => void;
}

/**
 * Neo-brutalist top navigation bar. Replaces the former fixed left sidebar on
 * desktop: brand block on the left, chunky nav tabs in the center, and an
 * actions cluster (connect bank, theme, notifications, user) on the right.
 * Below `lg`, the tabs collapse into a hamburger drawer that reuses Sidebar.
 */
export default function Header({
  title: _title,
  onConnectBank,
  canConnectBank,
  onLogout,
}: HeaderProps) {
  const { theme, toggleTheme } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);
  const user = useStore((s) => s.user);

  return (
    <header className="sticky top-0 z-30 border-b-2 border-border bg-background">
      <div className="flex h-16 items-center gap-3 px-4 md:px-6">
        {/* Mobile: hamburger opens the nav as a drawer */}
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger
            aria-label="Open navigation"
            className="grid h-9 w-9 place-items-center border-2 border-border bg-card text-foreground shadow-brutal-sm transition-all hover:-translate-x-0.5 hover:-translate-y-0.5 hover:shadow-brutal lg:hidden"
          >
            <Menu className="h-5 w-5" />
          </SheetTrigger>
          <SheetContent side="left" className="w-72 border-r-2 p-0">
            <Sidebar
              onConnectBank={onConnectBank}
              canConnectBank={canConnectBank}
              onLogout={onLogout}
              onNavigate={() => setMobileOpen(false)}
            />
          </SheetContent>
        </Sheet>

        {/* Brand */}
        <div className="flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center border-2 border-border bg-primary text-primary-foreground shadow-brutal-sm font-display text-lg font-bold">
            F
          </span>
          <span className="hidden font-display text-xl font-bold uppercase tracking-tight sm:inline">
            Finance-Tracker
          </span>
        </div>

        {/* Desktop nav tabs */}
        <nav className="ml-4 hidden flex-1 items-center gap-1 lg:flex">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2 border-2 border-transparent px-3 py-1.5 text-sm font-bold uppercase tracking-wide transition-all",
                  "text-foreground/70 hover:text-foreground",
                  isActive &&
                    "border-border bg-secondary text-secondary-foreground shadow-brutal-sm"
                )
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Spacer pushes actions right when nav is hidden */}
        <div className="flex-1 lg:hidden" />

        {/* Actions */}
        <div className="flex items-center gap-2">
          <button
            onClick={onConnectBank}
            disabled={!canConnectBank}
            className="hidden h-9 items-center gap-1.5 border-2 border-border bg-card px-2.5 text-xs font-bold uppercase tracking-wide text-foreground shadow-brutal-sm transition-all hover:-translate-x-0.5 hover:-translate-y-0.5 hover:shadow-brutal disabled:opacity-50 xl:flex whitespace-nowrap"
          >
            <Building2 className="h-4 w-4 shrink-0" />
            Connect Bank
          </button>

          <button
            onClick={toggleTheme}
            aria-label="Toggle theme"
            className="grid h-9 w-9 place-items-center border-2 border-border bg-card text-foreground shadow-brutal-sm transition-all hover:-translate-x-0.5 hover:-translate-y-0.5 hover:shadow-brutal"
          >
            {theme === "dark" ? (
              <Sun className="h-5 w-5" />
            ) : (
              <Moon className="h-5 w-5" />
            )}
          </button>

          <NotificationBell />

          <div className="hidden items-center gap-2 md:flex">
            <span className="grid h-9 w-9 place-items-center border-2 border-border bg-secondary text-sm font-bold text-secondary-foreground">
              {(user?.full_name || user?.username || "?").charAt(0).toUpperCase()}
            </span>
            <button
              onClick={onLogout}
              aria-label="Log out"
              className="grid h-9 w-9 place-items-center border-2 border-border bg-card text-foreground shadow-brutal-sm transition-all hover:-translate-x-0.5 hover:-translate-y-0.5 hover:shadow-brutal"
            >
              <LogOut className="h-5 w-5" />
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
