import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { Building2, Command, LogOut, Menu, Moon, Sun } from "lucide-react";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import NotificationBell from "@/components/custom/NotificationBell/NotificationBell";
import { useTheme } from "@/hooks/theme";
import { useStore } from "@/store/store";
import { useFlags } from "@/store/gameMode";
import { Brandmark } from "./Brandmark";
import { LevelPip } from "@/components/custom/LevelPip/LevelPip";
import Sidebar from "./Sidebar";
import { NavPalette } from "@/components/custom/NavPalette/NavPalette";
import { CommandDeck } from "@/components/custom/CommandDeck/CommandDeck";

interface HeaderProps {
  /** Page title (kept for API compatibility; rendered via PageHeader now). */
  title: string;
  onConnectBank: () => void;
  canConnectBank: boolean;
  onLogout: () => void;
}

/**
 * The masthead of the ledger: an engraved seal and wordmark on the left, a
 * "Jump to…" command affordance (⌘K), and the clerk's actions on the right. The
 * folio index itself lives in the left rail (SidebarRail, desktop) / the drawer
 * (mobile hamburger → Sheet → Sidebar).
 */
export default function Header({
  onConnectBank,
  canConnectBank,
  onLogout,
}: HeaderProps) {
  const { theme, toggleTheme } = useTheme();
  const { commandDeck } = useFlags();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const user = useStore((s) => s.user);
  const initial = (user?.full_name || user?.username || "?")
    .charAt(0)
    .toUpperCase();

  // ⌘/Ctrl-K opens the jump palette. The Chronicler owns `/`.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <header className="sticky top-0 z-30 border-b border-rule-strong/40 bg-background/90 backdrop-blur supports-[backdrop-filter]:bg-background/75">
      <div className="mx-auto flex h-[68px] w-full max-w-[1500px] items-center gap-4 px-4 md:px-6">
        {/* Mobile: hamburger opens the index as a drawer */}
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger
            aria-label="Open navigation"
            className="press grid h-11 w-11 place-items-center border border-rule-strong/50 bg-card text-foreground shadow-plate transition-all hover:bg-wash lg:hidden"
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

        {/* Jump-to command palette affordance */}
        <button
          onClick={() => setPaletteOpen(true)}
          aria-label="Jump to a page"
          className="press ml-1 flex items-center gap-2 border border-rule-strong/40 bg-card px-3 py-2 font-sans text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground shadow-plate transition-colors hover:text-foreground sm:ml-3"
        >
          <Command className="h-[14px] w-[14px]" />
          <span className="hidden sm:inline">Jump to…</span>
          <kbd className="ml-0.5 hidden font-mono text-[9px] text-muted-foreground/70 sm:inline">
            ⌘K
          </kbd>
        </button>

        <div className="flex-1" />

        {/* Clerk's actions */}
        <div className="flex items-center gap-2">
          <button
            onClick={onConnectBank}
            disabled={!canConnectBank}
            className="press hidden h-9 items-center gap-1.5 border border-rule-strong/50 bg-card px-3 font-sans text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground shadow-plate transition-all hover:bg-wash disabled:opacity-50 lg:flex"
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

      {commandDeck ? (
        <CommandDeck
          open={paletteOpen}
          onOpenChange={setPaletteOpen}
          onConnectBank={onConnectBank}
          canConnectBank={canConnectBank}
        />
      ) : (
        <NavPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      )}
    </header>
  );
}
