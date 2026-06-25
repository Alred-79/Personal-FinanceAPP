import { ReactNode, useRef, type PointerEvent as ReactPointerEvent } from "react";
import { motion, useMotionValue, useSpring } from "motion/react";
import { usePointerFine, useReducedMotion } from "@/hooks/useEnvironment";
import { cn } from "@/lib/utils";

/**
 * Magnetic hover — the child eases toward the pointer while it's over the
 * element, then springs back on leave. A small, premium micro-interaction for
 * primary CTAs. Fine-pointer only; renders inert (a plain wrapper) under reduced
 * motion or on touch.
 */
export function Magnetic({
  children,
  className,
  strength = 0.35,
}: {
  children: ReactNode;
  className?: string;
  strength?: number;
}) {
  const fine = usePointerFine();
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const sx = useSpring(x, { stiffness: 260, damping: 18 });
  const sy = useSpring(y, { stiffness: 260, damping: 18 });

  if (!fine || reduce) {
    return <div className={cn("inline-block", className)}>{children}</div>;
  }

  const onMove = (e: ReactPointerEvent) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    x.set((e.clientX - (r.left + r.width / 2)) * strength);
    y.set((e.clientY - (r.top + r.height / 2)) * strength);
  };
  const onLeave = () => {
    x.set(0);
    y.set(0);
  };

  return (
    <motion.div
      ref={ref}
      className={cn("inline-block", className)}
      style={{ x: sx, y: sy }}
      onPointerMove={onMove}
      onPointerLeave={onLeave}
    >
      {children}
    </motion.div>
  );
}
