import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useStore } from "@/store/store";
import { useFlags } from "@/store/gameMode";
import { Term } from "@/components/custom/Term/Term";
import { NAV_ITEMS, NAV_GROUPS } from "./nav";

/**
 * Persistent labeled desktop navigation. The four daily destinations stay
 * visible without hover; quieter groups preserve every existing route. The
 * mobile drawer
 * (Header hamburger → Sheet → Sidebar) is unchanged. Sits in normal theme so it
 * adapts to Ledger Paper / Midnight like the rest of the chrome.
 */
export default function SidebarRail() {
  const { gameLayer } = useFlags();
  const taxEnabled = useStore((s) => s.taxFeaturesEnabled);
  const freelancerEnabled = useStore((s) => s.freelancerModeEnabled);
  const items = NAV_ITEMS.filter(
    (i) =>
      (!i.gameOnly || gameLayer) &&
      (!i.taxOnly || taxEnabled) &&
      (!i.freelancerOnly || freelancerEnabled)
  );

  return (
    <aside className="sticky top-[68px] z-20 hidden h-[calc(100vh-68px)] w-64 shrink-0 flex-col gap-1 overflow-y-auto border-r border-rule-strong/40 bg-card/60 py-4 backdrop-blur lg:flex" aria-label="Primary navigation">
      {NAV_GROUPS.map(({ key, label }) => {
        const groupItems = items.filter((i) => i.group === key);
        if (groupItems.length === 0) return null;
        return (
          <div key={key} className="mb-1">
            <p className="h-5 overflow-hidden whitespace-nowrap px-4 font-sans text-[9px] uppercase tracking-[0.22em] text-muted-foreground/70">
              {label}
            </p>
            {groupItems.map(({ to, termKey, icon: Icon, folio }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  cn(
                    "relative flex min-h-11 items-center gap-3 border-l-2 border-transparent px-[18px] py-2.5 font-sans text-[12px] font-semibold uppercase tracking-[0.08em] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-gold",
                    "text-muted-foreground hover:bg-wash hover:text-foreground",
                    isActive && "border-gold bg-wash/60 text-foreground"
                  )
                }
              >
                <Icon className="h-[18px] w-[18px] shrink-0 opacity-80" />
                <span className="min-w-0 flex-1 overflow-hidden whitespace-nowrap">
                  <Term k={termKey} />
                </span>
                <span className="shrink-0 font-mono text-[9px] text-muted-foreground/50">
                  {folio}
                </span>
              </NavLink>
            ))}
          </div>
        );
      })}
    </aside>
  );
}
