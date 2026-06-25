import { useEffect } from "react";
import Lenis from "lenis";
import { useReducedMotion } from "@/hooks/useEnvironment";

/**
 * Lenis smooth scroll for the standalone landing page. The app's own Lenis lives
 * in AppShell, which /welcome does not use, so the landing wires its own single
 * rAF loop here (mirrors AppShell's setup). Disabled under reduced motion → the
 * browser's native scroll. The live instance is held in a module singleton so the
 * nav's in-page anchor links can smooth-scroll through it (see landingScrollTo).
 */
let current: Lenis | null = null;

/** Height of the fixed top register, so anchored sections don't hide beneath it. */
const NAV_OFFSET = -76;

/** Smooth-scroll to an in-page target (selector or element). Uses Lenis when it
 *  is running, else falls back to native scrollIntoView. */
export function landingScrollTo(target: string | HTMLElement) {
  if (current) {
    current.scrollTo(target, { offset: NAV_OFFSET });
    return;
  }
  const el = typeof target === "string" ? document.querySelector(target) : target;
  el?.scrollIntoView({ behavior: "smooth", block: "start" });
}

export function useLenis() {
  const reduce = useReducedMotion();
  useEffect(() => {
    if (reduce) return;
    const lenis = new Lenis();
    current = lenis;
    // Dev-only: expose for precise programmatic scrolling during verification.
    if (import.meta.env.DEV) (window as unknown as { __lenis?: Lenis }).__lenis = lenis;
    let raf = 0;
    const loop = (time: number) => {
      lenis.raf(time);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      lenis.destroy();
      current = null;
    };
  }, [reduce]);
}
