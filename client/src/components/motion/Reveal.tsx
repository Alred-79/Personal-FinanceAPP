import { ReactNode } from "react";
import { motion, type Variants } from "motion/react";
import { cn } from "@/lib/utils";
import { useReducedMotion } from "@/hooks/useEnvironment";

/**
 * frontend-elevation — a small reveal/stagger primitive so each page can
 * choreograph its own entrance (hero → supporting → detail) instead of every
 * card sharing one identical hover-tilt (the "uniform reflex" tell). Compose
 * `<Reveal>` (the stagger parent) around `<RevealItem>` blocks; order in the
 * DOM is the order they ink in. Under reduced motion both render as plain
 * divs, so content is always visible by default — never gated on a transition.
 *
 * `gap` tunes the stagger rhythm; `y`/`blur` tune how far/soft each block
 * arrives. Easing is the house ease-out-quint.
 */
const EASE = [0.23, 1, 0.32, 1] as const;

const parentVariants = (gap: number, delay: number): Variants => ({
  hidden: {},
  visible: { transition: { staggerChildren: gap, delayChildren: delay } },
});

const itemVariants = (y: number, blur: number): Variants => ({
  hidden: { opacity: 0, y, filter: blur ? `blur(${blur}px)` : undefined },
  visible: {
    opacity: 1,
    y: 0,
    filter: blur ? "blur(0px)" : undefined,
    transition: { duration: 0.55, ease: EASE },
  },
});

export function Reveal({
  children,
  className,
  gap = 0.07,
  delay = 0.03,
}: {
  children: ReactNode;
  className?: string;
  /** seconds between each child's entrance */
  gap?: number;
  /** seconds before the first child enters */
  delay?: number;
}) {
  const reduce = useReducedMotion();
  if (reduce) return <div className={className}>{children}</div>;
  return (
    <motion.div
      className={className}
      variants={parentVariants(gap, delay)}
      initial="hidden"
      animate="visible"
    >
      {children}
    </motion.div>
  );
}

export function RevealItem({
  children,
  className,
  y = 16,
  blur = 0,
}: {
  children: ReactNode;
  className?: string;
  /** vertical travel in px */
  y?: number;
  /** entry blur in px (0 = none) */
  blur?: number;
}) {
  const reduce = useReducedMotion();
  if (reduce) return <div className={cn(className)}>{children}</div>;
  return (
    <motion.div className={cn(className)} variants={itemVariants(y, blur)}>
      {children}
    </motion.div>
  );
}
