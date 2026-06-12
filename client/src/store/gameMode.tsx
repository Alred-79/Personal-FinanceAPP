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
}

function flagsFor(mode: GameMode): ModeFlags {
  return {
    gameLayer: mode !== "off",
    terminal: mode === "full",
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
