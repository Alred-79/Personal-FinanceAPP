import { useMemo } from "react";
import { motion } from "motion/react";
import { useReducedMotion } from "@/hooks/useEnvironment";

/**
 * An engraved habit-monster specimen — line-art in the banknote idiom. The body
 * shape is chosen (stably) from the seed so each creature differs; a `tamed`
 * specimen is inked in gold, an active one in heavy rule. In full mode the body
 * breathes and the eye blinks; reduced-motion renders it still. Amber/gold is
 * the game layer here — never boss red (these are lurkers, not the boss).
 */
const BODIES = [
  // kraken-ish coil
  "M20 70 q14 -26 40 -22 q18 -22 44 -8 q22 -2 30 14 q-10 8 -26 6 q6 14 -8 20 q-14 6 -22 -4 q-18 10 -34 0 q-16 -8 -24 -6 Z",
  // hydra-ish hump
  "M24 64 q20 -34 56 -28 q30 -8 56 16 q-8 16 -28 14 q4 16 -14 22 q-20 6 -30 -8 q-22 8 -38 -4 q-8 -10 -2 -24 Z",
  // leviathan-ish curl
  "M30 72 q6 -30 34 -30 q10 -18 32 -12 q26 4 30 28 q-2 18 -22 20 q-2 14 -20 12 q-20 -2 -22 -16 q-16 0 -12 -16 Z",
];
const SPINES = [
  "M104 56 q8 -10 18 -8 M112 64 q10 -6 18 -2",
  "M16 60 q-8 4 -6 14 M20 70 q-10 6 -8 16",
  "M96 44 l10 -12 M104 50 l14 -8",
];
const EYES = [
  { cx: 58, cy: 58 },
  { cx: 70, cy: 46 },
  { cx: 62, cy: 54 },
];

export function BestiaryCreature({
  seed,
  tamed = false,
  breathe = false,
  className,
}: {
  seed: number;
  tamed?: boolean;
  breathe?: boolean;
  className?: string;
}) {
  const reduce = useReducedMotion();
  const i = useMemo(() => Math.abs(seed) % BODIES.length, [seed]);
  const animate = breathe && !reduce;
  const color = tamed ? "hsl(var(--gold))" : "hsl(var(--rule-strong))";

  return (
    <svg viewBox="0 0 160 110" className={className} aria-hidden="true" focusable="false">
      <motion.g
        fill="none"
        stroke={color}
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ transformOrigin: "80px 60px" }}
        animate={animate ? { scale: [1, 1.025, 1] } : undefined}
        transition={animate ? { duration: 3.2, repeat: Infinity, ease: "easeInOut" } : undefined}
      >
        <path d={BODIES[i]} />
        <path d={SPINES[i]} />
        <circle cx={EYES[i].cx} cy={EYES[i].cy} r={2.4} fill={color} stroke="none" />
      </motion.g>
    </svg>
  );
}
