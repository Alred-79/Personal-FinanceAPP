/**
 * THROWAWAY dev harness — preview the final shell (left rail + ⌘K "Jump to"
 * header) and the game-mode atmosphere (off / ambient / full) without logging
 * in. Renders the REAL Header + SidebarRail + AtlasLayers against a tiny seeded
 * store. ◐ flips theme; the off/ambient/full buttons flip mode. Remove with the
 * other dev routes.
 */
import { useEffect, useState } from "react";
import { useStore } from "@/store/store";
import { useGameMode } from "@/store/gameMode";
import { cn } from "@/lib/utils";
import Header from "@/components/layout/Header";
import SidebarRail from "@/components/layout/SidebarRail";
import { AtlasLayers } from "@/components/atlas/AtlasLayers";

export default function DevNav() {
  const [dark, setDark] = useState(false);
  const { mode, setMode } = useGameMode();

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);
  useEffect(() => {
    useStore.setState({
      user: { id: 1, username: "advik", full_name: "Advik" } as never,
      isLoggedIn: true,
      taxFeaturesEnabled: true,
    });
  }, []);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <AtlasLayers />

      {/* dev controls */}
      <div className="fixed bottom-4 right-4 z-[9999] flex items-center gap-1 border border-rule-strong/50 bg-card p-1 shadow-plate">
        {(["off", "ambient", "full"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={cn(
              "px-2 py-1 font-mono text-[10px] uppercase tracking-[0.1em] transition-colors",
              mode === m ? "bg-gold text-background" : "text-muted-foreground hover:text-foreground"
            )}
          >
            {m}
          </button>
        ))}
        <button
          onClick={() => setDark((d) => !d)}
          className="ml-1 grid h-7 w-7 place-items-center border border-rule-strong/40 text-foreground"
        >
          ◐
        </button>
      </div>

      <Header
        title="Overview"
        onConnectBank={() => {}}
        canConnectBank={false}
        onLogout={() => {}}
      />

      <div className="flex flex-1">
        <SidebarRail />
        <main className="min-w-0 flex-1 px-4 py-8 md:px-8 lg:pl-6">
          <div className="mx-auto w-full max-w-[1400px] space-y-6">
            <div>
              <p className="dept-label">Form 1040-A · Nav preview</p>
              <h1 className="font-display text-4xl font-semibold">Overview</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Readability check — this text sits directly on the background.
                Mode: <span className="text-gold">{mode}</span>.
              </p>
            </div>
            <div className="plate p-6">
              <p className="dept-label">Statement</p>
              <p className="intaglio mt-2 text-5xl text-foreground">$35,666.00</p>
              <p className="mt-2 font-sans text-sm text-muted-foreground">
                A representative plate, to judge contrast over the atmosphere.
              </p>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
