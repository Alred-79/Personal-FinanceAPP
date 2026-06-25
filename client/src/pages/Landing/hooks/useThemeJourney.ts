import { RefObject, useEffect, useRef } from "react";
import {
  MotionValue,
  useMotionValueEvent,
  useScroll,
  useTransform,
} from "motion/react";
import { useReducedMotion } from "@/hooks/useEnvironment";

/**
 * Drives the light→dark handoff across the VaultDoor transition section.
 *
 * The handoff is an instant class flip (`.dark` toggled on the .landing-root
 * ancestor at the section's midpoint) — custom properties don't animate, so there
 * is no muddy mid-hue interpolation to see. The flip is masked by a "vault
 * curtain" veil whose opacity is a bell curve peaking exactly at the midpoint, so
 * the visitor perceives a darkening descent, not a snap.
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

  const apply = (wantDark: boolean) => {
    isDark.current = wantDark;
    const root = sectionRef.current?.closest(".landing-root");
    root?.classList.toggle("dark", wantDark);
  };

  useMotionValueEvent(scrollYProgress, "change", (p) => {
    if (reduce) return;
    const wantDark = p >= 0.5;
    if (wantDark !== isDark.current) apply(wantDark);
  });

  // Set the correct theme on mount (handles reduced motion + restored scroll pos).
  useEffect(() => {
    if (reduce) {
      apply(false);
      return;
    }
    apply(scrollYProgress.get() >= 0.5);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reduce]);

  return { curtain, progress: scrollYProgress, reduce };
}
