import { useMotionValue, useSpring, useMotionTemplate, motion } from "motion/react";
import { useEffect } from "react";
import { useReducedMotion, usePointerFine } from "@/hooks/useEnvironment";

/**
 * CursorGlow — a soft warm light that follows the cursor across the whole app,
 * giving the paper a sense of depth as you move (frontend-elevation). Fixed,
 * behind content, aria-hidden, pointer-events none. Off under reduced motion or
 * on touch. Mounted via AtlasLayers (ambient+full only).
 */
export function CursorGlow() {
  const reduce = useReducedMotion();
  const fine = usePointerFine();
  const gx = useSpring(useMotionValue(50), { stiffness: 60, damping: 20 });
  const gy = useSpring(useMotionValue(20), { stiffness: 60, damping: 20 });
  const bg = useMotionTemplate`radial-gradient(620px circle at ${gx}% ${gy}%, hsl(var(--gold) / 0.08), transparent 60%)`;

  useEffect(() => {
    if (reduce || !fine) return;
    const onMove = (e: PointerEvent) => {
      gx.set((e.clientX / window.innerWidth) * 100);
      gy.set((e.clientY / window.innerHeight) * 100);
    };
    window.addEventListener("pointermove", onMove);
    return () => window.removeEventListener("pointermove", onMove);
  }, [reduce, fine, gx, gy]);

  if (reduce || !fine) return null;
  return (
    <motion.div
      aria-hidden
      style={{ position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none", background: bg }}
    />
  );
}
