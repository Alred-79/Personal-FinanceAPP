import { useEffect, useRef, useState } from "react";
import {
  AnimatePresence,
  motion,
  useAnimationControls,
  useMotionValue,
  useSpring,
} from "motion/react";
import { useReducedMotion, usePointerFine } from "@/hooks/useEnvironment";
import { ClerkPortrait, type ClerkState } from "./ClerkPortrait";
import { ClerkTicket } from "./ClerkTicket";
import styles from "./ClerkPresence.module.css";

interface ClerkPresenceProps {
  /** Whether the Clerk's window is open (the launcher fades away when it is). */
  open: boolean;
  onOpen: () => void;
  /** The contextual offer for this section (the ticket text). */
  suggestionLabel?: string;
  /** When true, the Clerk taps the glass and the ticket unfurls unprompted. */
  autoNudge?: boolean;
  /** Click the ticket → open the window with the suggestion pre-filled. */
  onActivate?: () => void;
  /** Dismiss the auto-nudge → silence further nudges this session. */
  onSilence?: () => void;
  state?: ClerkState;
  /** Medallion diameter in px. */
  size?: number;
}

const clamp = (v: number) => (v < -1 ? -1 : v > 1 ? 1 : v);

/**
 * The floating Clerk: an engraved portrait medallion, bottom-right of every
 * page. It rests on a soft cast shadow, breathes almost imperceptibly, and (on
 * a fine pointer, motion allowed) follows the cursor with its eyes. When the
 * section has a contextual offer it surfaces a margin-note ticket — on hover
 * (always), or, at most once per section per session, unprompted with a single
 * "tap the glass" (a small hop + a radiating ring). Restrained by design.
 */
export function ClerkPresence({
  open,
  onOpen,
  suggestionLabel,
  autoNudge = false,
  onActivate,
  onSilence,
  state = "resting",
  size = 56,
}: ClerkPresenceProps) {
  const reduce = useReducedMotion();
  const fine = usePointerFine();
  const ref = useRef<HTMLButtonElement>(null);

  const gx = useSpring(useMotionValue(0), { stiffness: 120, damping: 18, mass: 0.6 });
  const gy = useSpring(useMotionValue(0), { stiffness: 120, damping: 18, mass: 0.6 });

  const knock = useAnimationControls();
  const [ringKey, setRingKey] = useState(0);
  const [hovered, setHovered] = useState(false);
  const hoverTimer = useRef<ReturnType<typeof setTimeout>>();

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

  // Tap the glass on the rising edge of an auto-nudge: a small hop + a ring.
  const prevNudge = useRef(false);
  useEffect(() => {
    if (autoNudge && !prevNudge.current && !reduce && !open) {
      knock.start({
        y: [0, -6, 0, -3, 0],
        transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] },
      });
      setRingKey((k) => k + 1);
    }
    prevNudge.current = autoNudge;
  }, [autoNudge, reduce, open, knock]);

  const onEnter = () => {
    if (!fine) return;
    clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(() => setHovered(true), 130);
  };
  const onLeave = () => {
    clearTimeout(hoverTimer.current);
    setHovered(false);
  };
  useEffect(() => () => clearTimeout(hoverTimer.current), []);

  const breathe =
    !reduce && !open ? { y: [0, -2.2, 0], scale: [1, 1.014, 1] } : { y: 0, scale: 1 };

  const showTicket = !open && !!suggestionLabel && (hovered || autoNudge);

  return (
    <div className={styles.anchor} onMouseEnter={onEnter} onMouseLeave={onLeave}>
      <AnimatePresence>
        {showTicket && (
          <ClerkTicket
            key="ticket"
            label={suggestionLabel as string}
            reduced={reduce}
            onActivate={() => onActivate?.()}
            onDismiss={
              autoNudge
                ? () => {
                    setHovered(false);
                    onSilence?.();
                  }
                : undefined
            }
          />
        )}
      </AnimatePresence>

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
        <motion.div className={styles.knock} animate={knock}>
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
              state={autoNudge ? "aware" : state}
            />
          </motion.span>
        </motion.div>
        {ringKey > 0 && (
          <motion.span
            key={ringKey}
            className={styles.ring}
            style={{ width: size, height: size }}
            initial={{ opacity: 0.5, scale: 0.85 }}
            animate={{ opacity: 0, scale: 1.7 }}
            transition={{ duration: 0.7, ease: "easeOut" }}
          />
        )}
      </motion.button>
    </div>
  );
}
