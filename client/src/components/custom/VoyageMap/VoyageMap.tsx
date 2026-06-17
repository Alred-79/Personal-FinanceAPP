import { useEffect, useRef } from "react";
import { useReducedMotion } from "@/hooks/useEnvironment";

interface Act {
  index: number;
  start: string;
  end: string;
}

/**
 * The Expedition voyage map (v4 §7.2, full-mode skin) — the month drawn as a
 * sea route: one port per act, the legs already sailed inked in gold, the legs
 * ahead dashed, and the ship at today's position. Decorative + additive: the
 * authoritative act/node list still renders beneath it (snapshot-pair safe).
 *
 * Engraved idiom: a faint rhumb grid, gold route, hollow ports ahead / filled
 * ports reached. Reduced-motion = a single static draw at the current leg.
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

/** Fraction (0..1) of the way through the month spanned by the acts. */
function monthProgress(acts: Act[]): number {
  if (acts.length === 0) return 0;
  const start = new Date(acts[0].start + "T00:00:00").getTime();
  const end = new Date(acts[acts.length - 1].end + "T00:00:00").getTime();
  if (!(end > start)) return 0;
  const now = Date.now();
  return Math.max(0, Math.min(1, (now - start) / (end - start)));
}

export function VoyageMap({
  acts,
  seed = 5,
  className,
}: {
  acts: Act[];
  seed?: number;
  className?: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const reduce = useReducedMotion();

  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const DPR = Math.min(window.devicePixelRatio || 1, 2);
    const css = getComputedStyle(document.documentElement);
    const C = (v: string) => `hsl(${css.getPropertyValue(v).trim()})`;

    const N = Math.max(1, acts.length); // legs
    const rng = mulberry32(seed * 7919 + 17);
    const ports = Array.from({ length: N + 1 }, (_, i) => ({
      x: 0.08 + (i / N) * 0.84,
      y: 0.5 + Math.sin(i * 1.3 + rng() * 6.28) * 0.22,
    }));
    const frac = monthProgress(acts); // 0..1 across the whole route
    const pos = frac * N; // distance along the route in leg-units
    let shown = pos;
    let raf = 0;

    function draw() {
      const cv2 = ref.current;
      if (!cv2 || !ctx) return;
      const r = cv2.getBoundingClientRect();
      const W = (cv2.width = Math.max(1, Math.floor(r.width * DPR)));
      const H = (cv2.height = Math.max(1, Math.floor(r.height * DPR)));
      ctx.clearRect(0, 0, W, H);

      // rhumb grid
      ctx.strokeStyle = C("--rule");
      ctx.globalAlpha = 0.3;
      ctx.lineWidth = DPR;
      for (let gx = 0; gx <= 10; gx++) {
        ctx.beginPath();
        ctx.moveTo((gx / 10) * W, 0);
        ctx.lineTo((gx / 10) * W, H);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;

      const cur = Math.floor(shown);
      const legProg = shown - cur;

      // route legs: sailed (gold solid) then ahead (dashed rule)
      ctx.lineWidth = 2 * DPR;
      for (let i = 0; i < N; i++) {
        const a = ports[i];
        const b = ports[i + 1];
        const sailed = i < cur;
        ctx.beginPath();
        ctx.strokeStyle = sailed ? C("--gold") : C("--rule-strong");
        ctx.globalAlpha = sailed ? 0.9 : 0.45;
        ctx.setLineDash(sailed ? [] : [5 * DPR, 5 * DPR]);
        ctx.moveTo(a.x * W, a.y * H);
        if (i === cur) {
          ctx.lineTo((a.x + (b.x - a.x) * legProg) * W, (a.y + (b.y - a.y) * legProg) * H);
        } else {
          ctx.lineTo(b.x * W, b.y * H);
        }
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
      }

      // ports
      ports.forEach((p, i) => {
        const reached = i <= cur;
        ctx.beginPath();
        ctx.fillStyle = reached ? C("--gold") : "transparent";
        ctx.strokeStyle = reached ? C("--gold") : C("--rule-strong");
        ctx.lineWidth = 1.6 * DPR;
        ctx.arc(p.x * W, p.y * H, 4 * DPR, 0, 6.2832);
        reached ? ctx.fill() : ctx.stroke();
        ctx.fillStyle = C("--muted-foreground");
        ctx.globalAlpha = 0.8;
        ctx.font = `${9.5 * DPR}px "Spline Sans Mono", monospace`;
        ctx.textAlign = "center";
        ctx.fillText(`▮ ${i + 1}`, p.x * W, p.y * H - 11 * DPR);
        ctx.globalAlpha = 1;
      });

      // the ship at the current position
      const a = ports[Math.min(cur, N)];
      const b = ports[Math.min(cur + 1, N)];
      const sx = (a.x + (b.x - a.x) * legProg) * W;
      const sy = (a.y + (b.y - a.y) * legProg) * H;
      ctx.fillStyle = C("--foreground");
      ctx.font = `${16 * DPR}px serif`;
      ctx.textAlign = "center";
      ctx.fillText("⛵", sx, sy + 5 * DPR);
    }

    if (reduce) {
      shown = pos;
      draw();
    } else {
      // sail in from the start to the current leg on mount.
      shown = 0;
      const aim = pos;
      const animate = () => {
        shown += (aim - shown) * 0.08;
        if (Math.abs(shown - aim) < 0.01) {
          shown = aim;
          draw();
          return;
        }
        draw();
        raf = requestAnimationFrame(animate);
      };
      raf = requestAnimationFrame(animate);
    }

    const ro = new ResizeObserver(() => draw());
    ro.observe(cv);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [acts, seed, reduce]);

  return (
    <canvas
      ref={ref}
      className={className}
      role="img"
      aria-label="This month's expedition route, drawn as a sea voyage with a port per act."
      style={{ display: "block", width: "100%", height: "100%" }}
    />
  );
}
