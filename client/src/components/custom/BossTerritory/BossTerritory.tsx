import { useEffect, useRef } from "react";
import { useReducedMotion } from "@/hooks/useEnvironment";

/**
 * The boss's held territory (v4 §7.1, full-mode skin) — a canvas region filled
 * in BOSS RED that recedes as the debt is paid down. `fraction` is the share of
 * the starting balance still owed (1 = full territory, 0 = vanquished). The red
 * here is the only sanctioned use of --boss-accent; the money figures around it
 * stay sober. Reduced-motion / coarse pointers get a single static draw.
 *
 * Engraved, not literal: a jagged coastline (seeded, stable per creditor) over
 * a hatched fill, with a faint gold survey grid above the waterline.
 */
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

export function BossTerritory({
  fraction,
  seed = 1,
  className,
}: {
  fraction: number;
  seed?: number;
  className?: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const reduce = useReducedMotion();
  // Animate the coastline from its previous position to the new one.
  const shown = useRef(fraction);

  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const DPR = Math.min(window.devicePixelRatio || 1, 2);
    const css = getComputedStyle(document.documentElement);
    const C = (v: string) => `hsl(${css.getPropertyValue(v).trim()})`;

    // Stable jagged coastline profile for this creditor.
    const rng = mulberry32(seed * 7919 + 17);
    const n = 64;
    const coast = Array.from({ length: n + 1 }, () => 0.78 + rng() * 0.34);

    let raf = 0;
    const target = Math.max(0, Math.min(1, fraction));

    function draw() {
      const cv2 = ref.current;
      if (!cv2 || !ctx) return;
      const r = cv2.getBoundingClientRect();
      const W = (cv2.width = Math.max(1, Math.floor(r.width * DPR)));
      const H = (cv2.height = Math.max(1, Math.floor(r.height * DPR)));
      ctx.clearRect(0, 0, W, H);
      const frac = shown.current;
      // waterline: top of the held territory (more owed → taller red region).
      const topY = (1 - frac) * H * 0.74 + H * 0.13;
      const coastY = (i: number) => topY * (0.86 + coast[i] * 0.16);

      // gold survey grid above the waterline (the reclaimed ground).
      ctx.strokeStyle = C("--gold");
      ctx.globalAlpha = 0.1;
      ctx.lineWidth = DPR;
      for (let gx = 0; gx <= n; gx += 6) {
        ctx.beginPath();
        ctx.moveTo((gx / n) * W, 0);
        ctx.lineTo((gx / n) * W, coastY(gx));
        ctx.stroke();
      }
      ctx.globalAlpha = 1;

      // the held territory: filled boss-red region with a struck coastline.
      const region = () => {
        ctx.beginPath();
        ctx.moveTo(0, H);
        for (let i = 0; i <= n; i++) ctx.lineTo((i / n) * W, coastY(i));
        ctx.lineTo(W, H);
        ctx.closePath();
      };
      region();
      ctx.fillStyle = C("--boss-accent");
      ctx.globalAlpha = 0.22;
      ctx.fill();
      ctx.globalAlpha = 0.7;
      ctx.lineWidth = 1.8 * DPR;
      ctx.strokeStyle = C("--boss-accent");
      ctx.stroke();
      ctx.globalAlpha = 1;

      // diagonal hatch clipped to the region (engraved shading).
      ctx.save();
      region();
      ctx.clip();
      ctx.strokeStyle = C("--boss-accent");
      ctx.globalAlpha = 0.12;
      ctx.lineWidth = DPR;
      for (let x = -H; x < W; x += 9 * DPR) {
        ctx.beginPath();
        ctx.moveTo(x, H);
        ctx.lineTo(x + H, 0);
        ctx.stroke();
      }
      ctx.restore();
      ctx.globalAlpha = 1;
    }

    function step() {
      shown.current += (target - shown.current) * 0.14;
      if (Math.abs(shown.current - target) < 0.002) {
        shown.current = target;
        draw();
        return;
      }
      draw();
      raf = requestAnimationFrame(step);
    }

    if (reduce) {
      shown.current = target;
      draw();
    } else {
      raf = requestAnimationFrame(step);
    }

    const ro = new ResizeObserver(() => draw());
    ro.observe(cv);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [fraction, seed, reduce]);

  return (
    <canvas
      ref={ref}
      className={className}
      role="img"
      aria-label="The debt's held territory — it recedes as the balance is paid down."
      style={{ display: "block", width: "100%", height: "100%" }}
    />
  );
}
