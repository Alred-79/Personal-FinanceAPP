import { useEffect, useRef } from "react";
import { motion, useMotionValue, useSpring } from "motion/react";
import { useReducedMotion, usePointerFine } from "@/hooks/useEnvironment";
import { ClerkPortrait, type ClerkState } from "./ClerkPortrait";
import styles from "./ClerkPresence.module.css";

interface ClerkPresenceProps {
  /** Whether the Clerk's window is open (the launcher fades away when it is). */
  open: boolean;
  onOpen: () => void;
  state?: ClerkState;
  /** Medallion diameter in px. */
  size?: number;
}

const clamp = (v: number) => (v < -1 ? -1 : v > 1 ? 1 : v);

/**
 * The floating Clerk: an engraved portrait medallion, bottom-right of every
 * page, that replaces the old MessageCircle button. It rests on a soft cast
 * shadow, breathes almost imperceptibly, and (on a fine pointer, motion
 * allowed) follows the cursor with its eyes — availability signalled by a
 * living presence, not a loud badge. Clicking opens the window; the launcher
 * then fades out so the window's own docked portrait carries the presence.
 *
 * The contextual "tap-the-glass" nudge and hover ticket arrive in P2.
 */
export function ClerkPresence({
  open,
  onOpen,
  state = "resting",
  size = 56,
}: ClerkPresenceProps) {
  const reduce = useReducedMotion();
  const fine = usePointerFine();
  const ref = useRef<HTMLButtonElement>(null);

  const gx = useSpring(useMotionValue(0), { stiffness: 120, damping: 18, mass: 0.6 });
  const gy = useSpring(useMotionValue(0), { stiffness: 120, damping: 18, mass: 0.6 });

  // Eyes follow the cursor while at rest. Off on coarse pointers, under reduced
  // motion, or while the window is open. A passive window listener sets motion
  // values directly — no React renders per move.
  useEffect(() => {
    if (!fine || reduce || open) {
      gx.set(0);
      gy.set(0);
      return;
    }
    const onMove = (e: PointerEvent) => {
      const el = ref.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      gx.set(clamp((e.clientX - cx) / 170));
      gy.set(clamp((e.clientY - cy) / 170));
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, [fine, reduce, open, gx, gy]);

  const breathe =
    !reduce && !open ? { y: [0, -2.2, 0], scale: [1, 1.014, 1] } : { y: 0, scale: 1 };

  return (
    <motion.button
      ref={ref}
      type="button"
      aria-label="Open the Clerk — your finance assistant"
      className={`${styles.root} assistant-button`}
      onClick={onOpen}
      animate={{ opacity: open ? 0 : 1, scale: open ? 0.6 : 1, y: open ? 8 : 0 }}
      transition={{ type: "spring", stiffness: 320, damping: 26 }}
      style={{ pointerEvents: open ? "none" : "auto" }}
      whileHover={reduce ? undefined : { scale: 1.04 }}
      whileTap={{ scale: 0.94 }}
    >
      <span className={styles.shadow} aria-hidden />
      <motion.span
        className={styles.disc}
        style={{ width: size, height: size }}
        animate={breathe}
        transition={{ duration: 5.2, ease: "easeInOut", repeat: Infinity }}
      >
        <ClerkPortrait
          size={Math.round(size * 0.92)}
          gazeX={fine && !reduce ? gx : undefined}
          gazeY={fine && !reduce ? gy : undefined}
          blink={!reduce}
          state={state}
        />
      </motion.span>
    </motion.button>
  );
}
