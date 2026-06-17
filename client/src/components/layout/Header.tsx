import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { Building2, ChevronDown, Command, LogOut, Menu, Moon, Sun } from "lucide-react";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import NotificationBell from "@/components/custom/NotificationBell/NotificationBell";
import { useTheme } from "@/hooks/theme";
import { useStore } from "@/store/store";
import { cn } from "@/lib/utils";
import { NAV_ITEMS, NAV_GROUPS, type NavItem } from "./nav";
import { Brandmark } from "./Brandmark";
import { Term } from "@/components/custom/Term/Term";
import { useFlags } from "@/store/gameMode";
import { LevelPip } from "@/components/custom/LevelPip/LevelPip";
import Sidebar from "./Sidebar";
import { NavPalette } from "@/components/custom/NavPalette/NavPalette";
import { NavVariantSwitch } from "./NavVariantSwitch";
import { useNavVariant } from "@/lib/navVariant";

interface HeaderProps {
  /** Page title (kept for API compatibility; rendered via PageHeader now). */
  title: string;
  onConnectBank: () => void;
  canConnectBank: boolean;
  onLogout: () => void;
}

/** Shared active-tab styling for the desktop folio index. */
const tabClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "group relative flex items-center gap-2 border-b-2 border-transparent px-3 py-2 font-sans text-[11px] font-semibold uppercase tracking-[0.16em] transition-colors",
    "text-muted-foreground hover:text-foreground",
    isActive && "border-gold text-foreground"
  );

/**
 * The masthead of the ledger: an engraved seal and wordmark on the left, the
 * folio index of pages running along a ruled baseline in the centre, and the
 * clerk's actions on the right. Below `lg` the index folds into a drawer that
 * reuses Sidebar (the dark "ledger cover").
 *
 * TEMP: the centre index has three switchable treatments (tabs + Tools overflow,
 * left sidebar rail, ⌘K palette) chosen via NavVariantSwitch.
 */
export default function Header({
  title: _title,
  onConnectBank,
  canConnectBank,
  onLogout,
}: HeaderProps) {
  const { theme, toggleTheme } = useTheme();
  const { gameLayer } = useFlags();
  const taxEnabled = useStore((s) => s.taxFeaturesEnabled);
  const navVariant = useNavVariant();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  // gameOnly nav entries (e.g. the Keeper) appear only when the game layer is
  // on; taxOnly entries only when the server tax flag is on; in off mode the
  // nav is exactly today's set (pixel-identity contract).
  const navItems = NAV_ITEMS.filter(
    (i) => (!i.gameOnly || gameLayer) && (!i.taxOnly || taxEnabled)
  );
  const ledgerItems = navItems.filter((i) => i.group === "ledger");
  const overflowItems = navItems.filter((i) => i.group !== "ledger");

  const user = useStore((s) => s.user);
  const initial = (user?.full_name || user?.username || "?")
    .charAt(0)
    .toUpperCase();

  // ⌘/Ctrl-K opens the jump palette (cmdk variant only). The Chronicler owns `/`.
  useEffect(() => {
    if (navVariant !== "cmdk") return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navVariant]);

  return (
    <header className="sticky top-0 z-30 border-b border-rule-strong/40 bg-background/90 backdrop-blur supports-[backdrop-filter]:bg-background/75">
      <div className="mx-auto flex h-[68px] w-full max-w-[1500px] items-center gap-4 px-4 md:px-6">
        {/* Mobile: hamburger opens the index as a drawer */}
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger
            aria-label="Open navigation"
            className="press grid h-9 w-9 place-items-center border border-rule-strong/50 bg-card text-foreground shadow-plate transition-all hover:bg-wash lg:hidden"
          >
            <Menu className="h-5 w-5" />
          </SheetTrigger>
          <SheetContent side="left" className="w-72 p-0">
            <Sidebar
              onConnectBank={onConnectBank}
              canConnectBank={canConnectBank}
              onLogout={onLogout}
              onNavigate={() => setMobileOpen(false)}
            />
          </SheetContent>
        </Sheet>

        {/* Seal + wordmark */}
        <NavLink to="/" className="group flex items-center gap-3">
          <span className="text-gold transition-transform duration-500 group-hover:rotate-[20deg]">
            <Brandmark size={38} />
          </span>
          <span className="hidden leading-none sm:block">
            <span className="block font-display text-lg font-semibold tracking-tight">
              The Ledger
            </span>
            <span className="dept-label text-[9px]">Personal Accounts</span>
          </span>
        </NavLink>

        {/* Desktop folio index — switchable treatment */}
        {navVariant === "sidebar" ? (
          // The left rail (in AppShell) is the index; keep the masthead spaced.
          <div className="hidden flex-1 lg:block" />
        ) : (
          <nav className="ml-3 hidden flex-1 items-stretch gap-0.5 lg:flex">
            {ledgerItems.map(({ to, termKey, icon: Icon }) => (
              <NavLink key={to} to={to} end={to === "/"} className={tabClass}>
                <Icon className="h-[15px] w-[15px] shrink-0 opacity-80" />
                <Term k={termKey} />
              </NavLink>
            ))}

            {navVariant === "tabs" && overflowItems.length > 0 && (
              <ToolsOverflow items={overflowItems} />
            )}

            {navVariant === "cmdk" && (
              <button
                onClick={() => setPaletteOpen(true)}
                className="ml-2 flex items-center gap-2 self-center border border-rule-strong/40 bg-card px-3 py-1.5 font-sans text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground shadow-plate transition-colors hover:text-foreground"
              >
                <Command className="h-[13px] w-[13px]" />
                Jump to…
                <kbd className="ml-1 font-mono text-[9px] text-muted-foreground/70">⌘K</kbd>
              </button>
            )}
          </nav>
        )}

        <div className="flex-1 lg:hidden" />

        {/* Clerk's actions */}
        <div className="flex items-center gap-2">
          {/* TEMP — nav style chooser */}
          <NavVariantSwitch />

          <button
            onClick={onConnectBank}
            disabled={!canConnectBank}
            className="press hidden h-9 items-center gap-1.5 border border-rule-strong/50 bg-card px-3 font-sans text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground shadow-plate transition-all hover:bg-wash disabled:opacity-50 xl:flex"
          >
            <Building2 className="h-4 w-4 shrink-0" />
            Link Bank
          </button>

          <button
            onClick={toggleTheme}
            aria-label="Toggle theme"
            className="press grid h-9 w-9 place-items-center border border-rule-strong/50 bg-card text-foreground shadow-plate transition-all hover:bg-wash"
          >
            {theme === "dark" ? (
              <Sun className="h-[18px] w-[18px]" />
            ) : (
              <Moon className="h-[18px] w-[18px]" />
            )}
          </button>

          <LevelPip />

          <NotificationBell />

          <div className="hidden items-center gap-2 md:flex">
            <span className="grid h-9 w-9 place-items-center rounded-full border border-gold/60 bg-gold/10 font-display text-sm font-semibold text-gold">
              {initial}
            </span>
            <button
              onClick={onLogout}
              aria-label="Log out"
              className="press grid h-9 w-9 place-items-center border border-rule-strong/50 bg-card text-foreground shadow-plate transition-all hover:bg-wash"
            >
              <LogOut className="h-[18px] w-[18px]" />
            </button>
          </div>
        </div>
      </div>

      {navVariant === "cmdk" && (
        <NavPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      )}
    </header>
  );
}

/** Variant A — the "Tools ▾" overflow popover for non-ledger entries. */
function ToolsOverflow({ items }: { items: NavItem[] }) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        className={cn(
          "group flex items-center gap-1.5 border-b-2 border-transparent px-3 py-2 font-sans text-[11px] font-semibold uppercase tracking-[0.16em] transition-colors",
          "text-muted-foreground hover:text-foreground data-[state=open]:text-foreground"
        )}
      >
        Tools
        <ChevronDown className="h-3.5 w-3.5 transition-transform group-data-[state=open]:rotate-180" />
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={6} className="w-60 p-2">
        {NAV_GROUPS.filter((g) => g.key !== "ledger").map(({ key, label }) => {
          const groupItems = items.filter((i) => i.group === key);
          if (groupItems.length === 0) return null;
          return (
            <div key={key} className="mb-1 last:mb-0">
              <p className="px-2 py-1 font-sans text-[9px] uppercase tracking-[0.22em] text-muted-foreground/60">
                {label}
              </p>
              {groupItems.map(({ to, termKey, icon: Icon, folio }) => (
                <NavLink
                  key={to}
                  to={to}
                  onClick={() => setOpen(false)}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-3 px-2 py-2 font-sans text-[12px] font-medium uppercase tracking-[0.1em] transition-colors",
                      "text-muted-foreground hover:bg-wash hover:text-foreground",
                      isActive && "text-gold"
                    )
                  }
                >
                  <Icon className="h-[15px] w-[15px] shrink-0 opacity-80" />
                  <span className="flex-1">
                    <Term k={termKey} />
                  </span>
                  <span className="font-mono text-[9px] text-muted-foreground/50">
                    {folio}
                  </span>
                </NavLink>
              ))}
            </div>
          );
        })}
      </PopoverContent>
    </Popover>
  );
}
