import { NavLink } from "react-router-dom";
import { Building2, LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { NAV_ITEMS } from "./nav";
import { Brandmark } from "./Brandmark";
import { Term } from "@/components/custom/Term/Term";
import { useStore } from "@/store/store";

interface SidebarProps {
  /** Opens the Plaid Link flow; disabled until the handler is ready. */
  onConnectBank: () => void;
  canConnectBank: boolean;
  onLogout: () => void;
  /** Called after navigating, so the mobile drawer can close itself. */
  onNavigate?: () => void;
}

/**
 * The dark "ledger cover": the folio index of the book, set in gold leaf on
 * leather. Used as the mobile navigation drawer.
 */
export default function Sidebar({
  onConnectBank,
  canConnectBank,
  onLogout,
  onNavigate,
}: SidebarProps) {
  const user = useStore((s) => s.user);

  return (
    <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
      {/* Cover plate */}
      <div className="flex h-[68px] items-center gap-3 border-b border-white/10 px-5">
        <span className="text-gold">
          <Brandmark size={34} />
        </span>
        <span className="leading-none">
          <span className="block font-display text-base font-semibold tracking-tight">
            The Ledger
          </span>
          <span className="text-[9px] font-semibold uppercase tracking-[0.3em] text-sidebar-foreground/50">
            Index of Folios
          </span>
        </span>
      </div>

      {/* Folio index */}
      <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-4">
        {NAV_ITEMS.map(({ to, termKey, icon: Icon, folio }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "group flex items-center gap-3 border-l-2 border-transparent px-3 py-2.5 font-sans text-[12px] font-semibold uppercase tracking-[0.14em] transition-colors",
                "text-sidebar-foreground/60 hover:bg-white/5 hover:text-sidebar-foreground",
                isActive && "border-gold bg-white/[0.04] text-gold"
              )
            }
          >
            <span className="w-6 shrink-0 font-mono text-[10px] tracking-normal text-sidebar-foreground/40 group-hover:text-sidebar-foreground/60">
              {folio}
            </span>
            <Icon className="h-[16px] w-[16px] shrink-0" />
            <Term k={termKey} />
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="space-y-1 border-t border-white/10 p-3">
        <button
          onClick={onConnectBank}
          disabled={!canConnectBank}
          className="flex w-full items-center gap-3 border-l-2 border-transparent px-3 py-2.5 font-sans text-[12px] font-semibold uppercase tracking-[0.14em] text-sidebar-foreground/60 transition-colors hover:bg-white/5 hover:text-sidebar-foreground disabled:opacity-50"
        >
          <span className="w-6 shrink-0" />
          <Building2 className="h-[16px] w-[16px] shrink-0" />
          Link Bank
        </button>

        <div className="flex items-center gap-3 px-3 py-2">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-gold/50 bg-gold/10 font-display text-sm font-semibold text-gold">
            {(user?.full_name || user?.username || "?").charAt(0).toUpperCase()}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate font-sans text-sm font-medium">
              {user?.full_name || user?.username || "Account Holder"}
            </p>
            <p className="text-[9px] uppercase tracking-[0.2em] text-sidebar-foreground/40">
              Authorised Clerk
            </p>
          </div>
          <button
            onClick={onLogout}
            aria-label="Log out"
            className="p-1.5 text-sidebar-foreground/50 transition-colors hover:text-sidebar-foreground"
          >
            <LogOut className="h-[16px] w-[16px]" />
          </button>
        </div>
      </div>
    </div>
  );
}
