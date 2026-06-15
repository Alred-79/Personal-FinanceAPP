import { useEffect, useState } from "react";

/**
 * Environment/accessibility hooks for the frontend-elevation Atlas layers.
 *
 * These gate expensive/animated chrome (living-guilloché, burin cursor,
 * parallax) so it never runs where it shouldn't: a user who asked for reduced
 * motion, or a touch device with no real pointer. They react to live changes
 * (e.g. the OS reduce-motion toggle) via matchMedia listeners.
 */

function useMediaQuery(query: string): boolean {
  // SSR/initial guard: matchMedia may be unavailable in non-browser test envs.
  const get = () =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(query).matches
      : false;

  const [matches, setMatches] = useState<boolean>(get);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

/** True when the user has requested reduced motion. Disable all decorative motion. */
export function useReducedMotion(): boolean {
  return useMediaQuery("(prefers-reduced-motion: reduce)");
}

/** True on a real fine pointer (mouse/trackpad). Gate hover/cursor effects off touch. */
export function usePointerFine(): boolean {
  return useMediaQuery("(hover: hover) and (pointer: fine)");
}
