import { useEffect, useState } from "react";
import {
  motion,
  useMotionValue,
  useTransform,
  type MotionValue,
} from "motion/react";
import { useReducedMotion } from "@/hooks/useEnvironment";

export type ClerkState =
  | "resting"
  | "aware"
  | "thinking"
  | "listening"
  | "speaking";

interface ClerkPortraitProps {
  /** Rendered px (square). */
  size?: number;
  /**
   * Gaze direction, each a MotionValue in roughly [-1, 1] (the spring-smoothed
   * cursor direction from the presence). Omit (header dock / reduced motion) and
   * the Clerk looks straight ahead.
   */
  gazeX?: MotionValue<number>;
  gazeY?: MotionValue<number>;
  /** Expression. Mostly "resting" today; later states nudge brow/mouth. */
  state?: ClerkState;
  /** Periodic blink. Parent passes false under reduced motion. */
  blink?: boolean;
  className?: string;
}

const clamp = (v: number) => (v < -1 ? -1 : v > 1 ? 1 : v);

/**
 * The Clerk — a banknote-style engraved portrait of a ledger clerk: eyeshade
 * visor, round spectacles, waistcoat + cravat + watch-chain, rendered as fine
 * single-ink line-work (everything is `currentColor`) the way a portrait is
 * engraved on currency. NOT a cartoon. The face is *rigged*: the pupils and a
 * faint head shift track `gaze`; the brow lifts when `state` is "aware"/
 * "thinking"; the eyes blink on a human-irregular cadence. The medallion casing
 * (paper disc, gold ring, cast shadow) is the caller's job — this draws only the
 * ink figure.
 */
export function ClerkPortrait({
  size = 56,
  gazeX,
  gazeY,
  state = "resting",
  blink = false,
  className,
}: ClerkPortraitProps) {
  // Hooks must be unconditional; fall back to a still value when no gaze given.
  const fallbackX = useMotionValue(0);
  const fallbackY = useMotionValue(0);
  const gx = gazeX ?? fallbackX;
  const gy = gazeY ?? fallbackY;

  // The whole face drifts a hair toward the cursor (parallax life); the pupils
  // travel further within the lenses.
  const headX = useTransform(gx, (v) => clamp(v) * 1.4);
  const headY = useTransform(gy, (v) => clamp(v) * 1.0);
  const pupilX = useTransform(gx, (v) => clamp(v) * 2.4);
  const pupilY = useTransform(gy, (v) => clamp(v) * 1.8);

  // Human-irregular blink: a quick squint every few seconds, never metronomic.
  const [blinking, setBlinking] = useState(false);
  useEffect(() => {
    if (!blink) return;
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      timer = setTimeout(() => {
        setBlinking(true);
        setTimeout(() => setBlinking(false), 130);
        schedule();
      }, 3200 + Math.random() * 3800);
    };
    schedule();
    return () => clearTimeout(timer);
  }, [blink]);

  const reduce = useReducedMotion();
  const browLift = state === "aware" || state === "thinking" ? -1.4 : 0;
  const speaking = state === "speaking" && !reduce;

  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <clipPath id="clerk-bust">
          <circle cx="50" cy="50" r="38.5" />
        </clipPath>
      </defs>

      {/* ── Frame: engine-turned ring + double hairline ───────────── */}
      <g stroke="currentColor" fill="none">
        <circle cx="50" cy="50" r="47" strokeWidth="1.3" />
        <circle cx="50" cy="50" r="40.5" strokeWidth="0.6" opacity="0.5" />
        {Array.from({ length: 90 }).map((_, i) => {
          const a = (i / 90) * Math.PI * 2;
          return (
            <line
              key={i}
              x1={50 + 42.5 * Math.cos(a)}
              y1={50 + 42.5 * Math.sin(a)}
              x2={50 + 46 * Math.cos(a)}
              y2={50 + 46 * Math.sin(a)}
              strokeWidth="0.5"
              opacity="0.55"
            />
          );
        })}
      </g>

      {/* ── The bust, clipped to the inner medallion ──────────────── */}
      <g clipPath="url(#clerk-bust)">
        {/* faint engraved field behind the figure */}
        <g stroke="currentColor" strokeWidth="0.4" opacity="0.1">
          {Array.from({ length: 22 }).map((_, i) => (
            <line key={i} x1="11" y1={16 + i * 3.4} x2="89" y2={16 + i * 3.4} />
          ))}
        </g>

        {/* coat: shoulders, lapels, collar, cravat knot + tie, watch-chain */}
        <g stroke="currentColor" fill="none" strokeWidth="1.1" strokeLinejoin="round">
          <path
            d="M15,90 C19,71 31,63 50,63 C69,63 81,71 85,90"
            fill="hsl(var(--foreground) / 0.05)"
          />
          <path d="M50,64 L41.5,90" opacity="0.6" />
          <path d="M50,64 L58.5,90" opacity="0.6" />
          <path d="M42,68 L34,90" opacity="0.4" />
          <path d="M58,68 L66,90" opacity="0.4" />
          <path d="M44,63 L50,69 L56,63" />
          <path d="M48,65 L50,70 L52,65 Z" fill="hsl(var(--foreground) / 0.1)" strokeWidth="0.9" />
          <path d="M49,71 L48.4,80 M51,71 L51.6,80" strokeWidth="0.7" opacity="0.5" />
          <path d="M43,75 Q50,80 57,75" strokeWidth="0.6" opacity="0.5" strokeDasharray="0.9 1.3" />
          <g strokeWidth="0.45" opacity="0.28">
            <path d="M23,84 q5,-9 14,-13" />
            <path d="M77,84 q-5,-9 -14,-13" />
          </g>
        </g>

        {/* neck */}
        <path
          d="M46,55 L46,62 Q50,65 54,62 L54,55"
          stroke="currentColor"
          fill="hsl(var(--foreground) / 0.04)"
          strokeWidth="0.9"
          opacity="0.85"
        />

        {/* ── Head group: drifts toward the cursor ────────────────── */}
        <motion.g style={{ x: headX, y: headY }}>
          {/* skull */}
          <ellipse
            cx="50"
            cy="42"
            rx="14"
            ry="16.5"
            stroke="currentColor"
            fill="hsl(var(--foreground) / 0.03)"
            strokeWidth="1.1"
          />
          {/* ears */}
          <path d="M36,43 q-2.3,1.6 0,4.2" stroke="currentColor" fill="none" strokeWidth="0.9" />
          <path d="M64,43 q2.3,1.6 0,4.2" stroke="currentColor" fill="none" strokeWidth="0.9" />

          {/* cheek / jaw tone */}
          <g stroke="currentColor" strokeWidth="0.4" opacity="0.22" fill="none">
            <path d="M38.5,49 q-1.2,4 1.4,7.5" />
            <path d="M61.5,49 q1.2,4 -1.4,7.5" />
          </g>

          {/* hair crown */}
          <g stroke="currentColor" strokeWidth="0.5" fill="none" opacity="0.5">
            <path d="M37,32 Q50,21.5 63,32" />
            <path d="M38.5,30 Q50,22 61.5,30" />
            <path d="M40,28.2 Q50,23 60,28.2" opacity="0.7" />
            <path d="M37.2,33 l-0.4,4" opacity="0.6" />
            <path d="M62.8,33 l0.4,4" opacity="0.6" />
          </g>

          {/* eyeshade: band + translucent brim + cast shadow */}
          <g>
            <path d="M37,34.6 Q50,32.3 63,34.6" stroke="currentColor" strokeWidth="0.9" fill="none" />
            <path
              d="M36.5,35.6 Q50,40.6 63.5,35.6 Q62.5,41 50,41.4 Q37.5,41 36.5,35.6 Z"
              stroke="currentColor"
              strokeWidth="1.0"
              fill="hsl(var(--foreground) / 0.13)"
            />
            <g stroke="currentColor" strokeWidth="0.4" opacity="0.4">
              <path d="M41,36.9 Q50,38.9 59,36.9" />
            </g>
            {/* brim cast shadow onto the brow */}
            <path d="M39,42 Q50,43.4 61,42" stroke="currentColor" strokeWidth="0.5" fill="none" opacity="0.22" />
          </g>

          {/* brow (lifts when aware/thinking) */}
          <motion.g
            stroke="currentColor"
            strokeWidth="0.7"
            fill="none"
            opacity="0.65"
            animate={{ y: browLift }}
            transition={{ type: "spring", stiffness: 300, damping: 24 }}
          >
            <path d="M38,43.4 Q42,42 46,43.4" />
            <path d="M54,43.4 Q58,42 62,43.4" />
          </motion.g>

          {/* spectacles */}
          <g stroke="currentColor" fill="none" strokeWidth="1.1">
            <circle cx="41.5" cy="47" r="5" />
            <circle cx="58.5" cy="47" r="5" />
            <path d="M46.5,46.6 Q50,45.3 53.5,46.6" />
            <path d="M36.6,46.2 L33.5,45.2" strokeWidth="0.8" />
            <path d="M63.4,46.2 L66.5,45.2" strokeWidth="0.8" />
          </g>

          {/* eyes: pupils track gaze; a blink cross-fades open→closed lids
              (cross-fade dodges SVG transform-origin browser inconsistencies). */}
          <motion.g style={{ x: pupilX, y: pupilY }}>
            <motion.g
              initial={false}
              animate={{ opacity: blinking ? 0 : 1 }}
              transition={{ duration: 0.06, ease: "easeOut" }}
            >
              <circle cx="41.5" cy="47.6" r="1.6" fill="currentColor" />
              <circle cx="58.5" cy="47.6" r="1.6" fill="currentColor" />
            </motion.g>
            <motion.g
              initial={false}
              stroke="currentColor"
              strokeWidth="1"
              strokeLinecap="round"
              fill="none"
              animate={{ opacity: blinking ? 1 : 0 }}
              transition={{ duration: 0.06, ease: "easeOut" }}
            >
              <path d="M39,47.8 q2.5,1.4 5,0" />
              <path d="M55,47.8 q2.5,1.4 5,0" />
            </motion.g>
          </motion.g>

          {/* nose */}
          <path
            d="M50,48.6 L48.7,53.6 Q50,54.5 51.3,53.6"
            stroke="currentColor"
            fill="none"
            strokeWidth="0.8"
            opacity="0.8"
          />

          {/* moustache (static) + a mouth that opens when speaking */}
          <g stroke="currentColor" fill="none">
            <path d="M43.5,56.6 Q50,59.2 56.5,56.6" strokeWidth="1.5" />
            <motion.path
              d="M47,58.8 Q50,59.4 53,58.8"
              strokeWidth="0.6"
              style={{ transformBox: "fill-box", transformOrigin: "center" }}
              initial={false}
              animate={
                speaking
                  ? { scaleY: [1, 2.6, 0.7, 2.1, 1], opacity: [0.4, 0.7, 0.45, 0.7, 0.4] }
                  : { scaleY: 1, opacity: 0.4 }
              }
              transition={
                speaking
                  ? { duration: 0.46, repeat: Infinity, ease: "easeInOut" }
                  : { duration: 0.2 }
              }
            />
          </g>
        </motion.g>
      </g>
    </svg>
  );
}
