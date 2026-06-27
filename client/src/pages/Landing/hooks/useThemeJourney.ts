import { RefObject, useEffect, useRef } from "react";
import {
  MotionValue,
  useMotionValueEvent,
  useScroll,
  useTransform,
} from "motion/react";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { useVaultLights } from "./useVaultLights";

/**
 * Drives the light→dark handoff across the VaultDoor transition section.
 *
 * The handoff is an instant class flip (`.dark` toggled on the .landing-root
 * ancestor at the section's midpoint) — custom properties don't animate, so there
 * is no muddy mid-hue interpolation to see. The flip is masked by a "vault
 * curtain" veil whose opacity is a bell curve peaking exactly at the midpoint, so
 * the visitor perceives a darkening descent, not a snap.
 *
 * Manual override: the vault light-switch (useVaultLights) can force the dark zone
 * back to light — when `lightsOn` is true the final theme stays light even past the
 * midpoint. The hook also publishes `inDarkZone` (true once at/below the midpoint)
 * so the switch knows when to appear; it's the vault's own control and exists only
 * there.
 *
 * Returns the curtain opacity and the raw scroll progress (for the door visual).
 * Under reduced motion: no curtain, no flip — the page stays in the light theme.
 */
export function useThemeJourney(sectionRef: RefObject<HTMLElement>): {
  curtain: MotionValue<number>;
  progress: MotionValue<number>;
  reduce: boolean;
} {
  const reduce = useReducedMotion();
  const { lightsOn, setInDarkZone } = useVaultLights();
  const { scrollYProgress } = useScroll({
    target: sectionRef,
    offset: ["start end", "end start"],
  });

  // Bell curve, with a short high plateau around the midpoint to cover the flip.
  const curtain = useTransform(
    scrollYProgress,
    [0, 0.42, 0.5, 0.58, 1],
    [0, 0.9, 0.97, 0.9, 0]
  );

  const isDark = useRef(false);
  const lightsRef = useRef(lightsOn);
  lightsRef.current = lightsOn;

  // Final theme = past-the-midpoint AND lights not manually switched on.
  const apply = (pastMid: boolean) => {
    const wantDark = pastMid && !lightsRef.current;
    isDark.current = wantDark;
    const root = sectionRef.current?.closest(".landing-root");
    root?.classList.toggle("dark", wantDark);
  };

  useMotionValueEvent(scrollYProgress, "change", (p) => {
    if (reduce) return;
    const pastMid = p >= 0.5;
    setInDarkZone(pastMid);
    apply(pastMid);
  });

  // Re-apply on mount AND whenever the lights are switched (so flipping the switch
  // recolors the vault live, without waiting for the next scroll event).
  useEffect(() => {
    if (reduce) {
      apply(false);
      setInDarkZone(false);
      return;
    }
    const pastMid = scrollYProgress.get() >= 0.5;
    setInDarkZone(pastMid);
    apply(pastMid);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reduce, lightsOn]);

  return { curtain, progress: scrollYProgress, reduce };
}
