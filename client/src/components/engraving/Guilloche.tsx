import { useMemo } from "react";
import { cn } from "@/lib/utils";

/**
 * Parametric guilloché — the interleaved engraved curves used on banknotes
 * and certificates. Each instance is generated from a seed, so every plate
 * in the app carries a different (but stable) engraving.
 */

/** Deterministic PRNG so a given seed always engraves the same plate. */
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** One ring of a rosette: a perturbed rose curve sampled into a path. */
function ringPath(
  cx: number,
  cy: number,
  R: number,
  k1: number,
  k2: number,
  amp1: number,
  amp2: number,
  phase: number,
  steps = 540
): string {
  const pts: string[] = [];
  for (let i = 0; i <= steps; i++) {
    const t = (i / steps) * Math.PI * 2;
    const r =
      R *
      (1 +
        amp1 * Math.sin(k1 * t + phase) +
        amp2 * Math.sin(k2 * t - phase * 1.7));
    const x = cx + r * Math.cos(t);
    const y = cy + r * Math.sin(t);
    pts.push(`${x.toFixed(2)},${y.toFixed(2)}`);
  }
  return `M${pts.join("L")}Z`;
}

export interface GuillocheProps {
  /** Rendered width/height in px (square). */
  size?: number;
  /** Number of concentric engraved rings. */
  rings?: number;
  /** Seed: same seed → same engraving. Vary per plate. */
  seed?: number;
  /** Slow ceremonial rotation. */
  animate?: boolean;
  strokeWidth?: number;
  className?: string;
}

export function Guilloche({
  size = 320,
  rings = 7,
  seed = 1,
  animate = false,
  strokeWidth = 0.6,
  className,
}: GuillocheProps) {
  const paths = useMemo(() => {
    const rand = mulberry32(seed * 7919 + 17);
    const out: { d: string; opacity: number }[] = [];
    const c = 200; // internal viewBox is 400x400
    for (let i = 0; i < rings; i++) {
      const R = 60 + (i / Math.max(1, rings - 1)) * 120;
      const k1 = 5 + Math.floor(rand() * 9); // petal counts
      const k2 = 11 + Math.floor(rand() * 13);
      const amp1 = 0.05 + rand() * 0.16;
      const amp2 = 0.02 + rand() * 0.07;
      const phase = rand() * Math.PI * 2;
      out.push({
        d: ringPath(c, c, R, k1, k2, amp1, amp2, phase),
        opacity: 0.25 + 0.55 * (1 - i / rings),
      });
    }
    return out;
  }, [rings, seed]);

  return (
    <svg
      viewBox="0 0 400 400"
      width={size}
      height={size}
      className={cn(animate && "animate-rotate-slow", className)}
      aria-hidden="true"
      focusable="false"
    >
      {paths.map((p, i) => (
        <path
          key={i}
          d={p.d}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          opacity={p.opacity}
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  );
}

export interface GuillocheBandProps {
  /** Height of the band in px; width is fluid. */
  height?: number;
  /** Number of interleaved waves. */
  waves?: number;
  seed?: number;
  className?: string;
}

/** The woven border strip that runs along the edge of a banknote. */
export function GuillocheBand({
  height = 22,
  waves = 4,
  seed = 3,
  className,
}: GuillocheBandProps) {
  const paths = useMemo(() => {
    const rand = mulberry32(seed * 104729 + 31);
    const out: string[] = [];
    const W = 1200;
    const H = 40;
    for (let w = 0; w < waves; w++) {
      const amp = 6 + rand() * 9;
      const freq = 2 + Math.floor(rand() * 4);
      const phase = rand() * Math.PI * 2;
      const mid = H / 2;
      const pts: string[] = [];
      for (let x = 0; x <= W; x += 8) {
        const y =
          mid +
          amp * Math.sin((x / W) * Math.PI * 2 * freq + phase) +
          (amp / 3) * Math.sin((x / W) * Math.PI * 2 * freq * 2.7 - phase);
        pts.push(`${x},${y.toFixed(2)}`);
      }
      out.push(`M${pts.join("L")}`);
    }
    return out;
  }, [waves, seed]);

  return (
    <svg
      viewBox="0 0 1200 40"
      preserveAspectRatio="none"
      style={{ height, width: "100%", display: "block" }}
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      {paths.map((d, i) => (
        <path
          key={i}
          d={d}
          fill="none"
          stroke="currentColor"
          strokeWidth={0.8}
          opacity={0.5 - i * 0.08}
        />
      ))}
    </svg>
  );
}

/** A small corner rosette for certificate plates. */
export function CornerRosette({
  size = 56,
  seed = 5,
  className,
}: {
  size?: number;
  seed?: number;
  className?: string;
}) {
  return (
    <Guilloche
      size={size}
      rings={4}
      seed={seed}
      strokeWidth={0.5}
      className={className}
    />
  );
}
