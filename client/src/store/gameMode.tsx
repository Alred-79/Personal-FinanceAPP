/**
 * GameModeProvider — the one game-intensity variable, end to end (v4 §10.2).
 *
 * `mode ∈ {off, ambient, full}` drives exactly: the design tokens (via the
 * `data-mode` attribute on <html>), the copy term catalog, and feature-presence
 * flags. NO component branches on `mode` directly — they read `flags`, call
 * `useTerm`, or render `<Term/>`. (A grep test enforces this.)
 *
 * The mode is persisted server-side through the settings API. Before settings
 * resolve, the provider stays in `off` so a pure-finance user never sees a flash
 * of game chrome.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import api from "@/lib/api";
import offTerms from "@/terms/terms.off.json";
import ambientTerms from "@/terms/terms.ambient.json";
import fullTerms from "@/terms/terms.full.json";

export type GameMode = "off" | "ambient" | "full";

const CATALOGS: Record<GameMode, Record<string, string>> = {
  off: offTerms,
  ambient: ambientTerms,
  full: fullTerms,
};

/** Feature-presence flags derived from the mode — the ONLY way a component
 * learns "is this game feature on". Later packages extend this shape. */
export interface ModeFlags {
  /** Any game chrome at all (ambient + full). */
  gameLayer: boolean;
  /** Full terminal styling: scanlines, amber accents, game vocabulary. */
  terminal: boolean;

  /* ── frontend-elevation ("Cartographer's Desk") flags ──────────────────
     Atlas/Deck surfaces. FINANCE tools (commandDeck, moodWatermark, the
     guilloché SHAPE) are on in every mode incl. off; GAME surfaces and the
     richer MOTION are ambient+ or full-only. As ever, components read these
     flags — never branch on `mode` directly. */

  /** The Command Deck (⌘K) — a finance tool; available in every mode. */
  commandDeck: boolean;
  /** Living-guilloché background MOTION (breathe). off = frozen static shape. */
  guillocheMotion: boolean;
  /** Full-only living-guilloché extras: cursor-warp + WebGL phosphor. */
  guillocheWarp: boolean;
  /** The engraver's-burin cursor + ink trail (ambient + full). */
  burin: boolean;
  /** Mood watermark present in every mode; time-of-day ink warming = full only. */
  moodTimeOfDay: boolean;
  /** Game collectibles: Cabinet, minted coins, bestiary (ambient + full). */
  cabinet: boolean;
  bestiary: boolean;
}

function flagsFor(mode: GameMode): ModeFlags {
  const game = mode !== "off";
  const full = mode === "full";
  return {
    gameLayer: game,
    terminal: full,
    commandDeck: true,      // finance tool — every mode
    guillocheMotion: game,  // off = frozen static shape
    guillocheWarp: full,
    burin: game,
    moodTimeOfDay: full,
    cabinet: game,
    bestiary: game,
  };
}

interface GameModeContextValue {
  mode: GameMode;
  setMode: (mode: GameMode) => void;
  /** Look up a term in the current catalog, falling back to the off value. */
  term: (key: string) => string;
  /** The off-catalog value for a key — the always-reachable plain label. */
  plainTerm: (key: string) => string;
  flags: ModeFlags;
}

const GameModeContext = createContext<GameModeContextValue | null>(null);

/**
 * Logout reset bridge. The provider holds game mode in React state, so the
 * non-React store (store.ts logout) can't reset it directly. The mounted
 * provider registers a setter here; resetGameMode() drives every live provider
 * back to the off default so game chrome never survives a logout. Module-level
 * (not per-user) — this is a single-user app and the mode is global state.
 */
const resetters = new Set<() => void>();
export function resetGameMode() {
  resetters.forEach((fn) => fn());
}

const VALID: readonly GameMode[] = ["off", "ambient", "full"];

function isMode(value: unknown): value is GameMode {
  return typeof value === "string" && (VALID as readonly string[]).includes(value);
}

export function GameModeProvider({ children }: { children: ReactNode }) {
  // Default to off until settings resolve — never flash game chrome.
  const [mode, setModeState] = useState<GameMode>("off");

  // Load the persisted mode once on mount.
  useEffect(() => {
    let cancelled = false;
    api
      .get("/settings/")
      .then((res) => {
        const persisted = res.data?.preferences?.game_mode;
        if (!cancelled && isMode(persisted)) setModeState(persisted);
      })
      .catch(() => {
        /* stay in off — pure finance is the safe default */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Reflect the mode onto <html data-mode> synchronously so token CSS applies
  // in the same paint. This is the single place the attribute is written.
  useEffect(() => {
    document.documentElement.dataset.mode = mode;
  }, [mode]);

  // Register a logout reset hook so store.logout() can drive this provider back
  // to off (the safe pure-finance default) when the user signs out.
  useEffect(() => {
    const reset = () => setModeState("off");
    resetters.add(reset);
    return () => {
      resetters.delete(reset);
    };
  }, []);

  const setMode = useCallback((next: GameMode) => {
    // Optimistic local switch (synchronous, no reload) + persist to the server.
    setModeState(next);
    api
      .put("/settings/preferences/", { game_mode: next })
      .catch(() => {
        /* best-effort persist; the live switch already happened */
      });
  }, []);

  const value = useMemo<GameModeContextValue>(() => {
    const catalog = CATALOGS[mode];
    const off = CATALOGS.off;
    return {
      mode,
      setMode,
      term: (key: string) => catalog[key] ?? off[key] ?? key,
      plainTerm: (key: string) => off[key] ?? key,
      flags: flagsFor(mode),
    };
  }, [mode, setMode]);

  return (
    <GameModeContext.Provider value={value}>
      {children}
    </GameModeContext.Provider>
  );
}

/** The full provider API. Allowed to read `mode` directly. */
export function useGameMode(): GameModeContextValue {
  const ctx = useContext(GameModeContext);
  if (ctx === null) {
    // Defensive default so a component rendered outside the provider (e.g. an
    // isolated test) still works in pure-finance off mode.
    return {
      mode: "off",
      setMode: () => {},
      term: (key: string) => CATALOGS.off[key] ?? key,
      plainTerm: (key: string) => CATALOGS.off[key] ?? key,
      flags: flagsFor("off"),
    };
  }
  return ctx;
}

/** Feature flags only — the sanctioned way for a component to gate game UI. */
export function useFlags(): ModeFlags {
  return useGameMode().flags;
}

/**
 * Resolve a single term key for the current mode. Falls back to the off value,
 * then the key itself. Logs once (dev only) on a missing key.
 */
export function useTerm(key: string): string {
  const { term } = useGameMode();
  const value = term(key);
  if (import.meta.env.DEV && !(key in CATALOGS.off)) {
    console.warn(`useTerm: unknown term key "${key}"`);
  }
  return value;
}
