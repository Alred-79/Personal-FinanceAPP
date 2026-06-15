import { useEffect, useRef } from "react";
import { useFlags } from "@/store/gameMode";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { mulberry32 } from "@/lib/prng";

/**
 * LivingGuilloche — the full-bleed engraved rosette behind the whole app.
 *
 * One global instance (mounted in AppShell). Canvas 2D, fixed center (it does
 * NOT follow the cursor — a deliberate decision so the background stays calm).
 *
 * Mode behaviour (via flags, never `mode` directly):
 *   off        → not rendered at all (pixel-honest pure finance).
 *   ambient    → the rosette breathes (slow amplitude drift). [guillocheMotion]
 *   full       → breathe + (future) cursor-warp/phosphor.       [guillocheWarp]
 *   reduce-motion → a single static frame (no rAF loop).
 *
 * Data-seeded: the ring parameters come from `seed` (a net-worth/month-derived
 * value) so each user's banknote shape is uniquely, stably theirs.
 *
 * Color law: drawn in `--rule-strong` at low opacity, sits at z-0 behind
 * everything; never touches a money figure.
 */
export function LivingGuilloche({ seed = 421018 }: { seed?: number }) {
  const flags = useFlags();
  const reduce = useReducedMotion();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // The background is finance-neutral chrome but reads as "alive" → only show it
  // once the game layer is on (ambient+). off mode stays pure.
  const visible = flags.guillocheMotion || flags.guillocheWarp;
  const animate = (flags.guillocheMotion || flags.guillocheWarp) && !reduce;

  useEffect(() => {
    if (!visible) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const DPR = Math.min(window.devicePixelRatio || 1, 2);
    let raf = 0;
    let t = 0;
    let running = true;

    // Read the stroke color from the live theme so light/dark both work.
    const strokeColor = () =>
      `hsl(${getComputedStyle(document.documentElement)
        .getPropertyValue("--rule-strong")
        .trim()})`;

    // Deterministic per-ring parameters from the data seed.
    const rings = 9;
    const rng = mulberry32(seed * 7919 + 17);
    const params = Array.from({ length: rings }, () => ({
      k1: 3 + Math.floor(rng() * 9),
      k2: 2 + Math.floor(rng() * 7),
      ph: rng() * Math.PI * 2,
    }));

    let W = 0;
    let H = 0;
    function resize() {
      W = canvas!.width = Math.floor(window.innerWidth * DPR);
      H = canvas!.height = Math.floor(window.innerHeight * DPR);
      canvas!.style.width = window.innerWidth + "px";
      canvas!.style.height = window.innerHeight + "px";
    }
    resize();
    window.addEventListener("resize", resize);

    function frame() {
      if (!running) return;
      if (animate) t += 0.005;
      ctx!.clearRect(0, 0, W, H);
      ctx!.strokeStyle = strokeColor();
      ctx!.lineWidth = DPR * 0.6;
      const cx = W * 0.5;
      const cy = H * 0.5;
      const base = Math.min(W, H) * 0.46;
      for (let r = 0; r < rings; r++) {
        const p = params[r];
        ctx!.globalAlpha = 0.5 - r * 0.045;
        ctx!.beginPath();
        // breathing amplitude (static when !animate → renders one frame)
        const amp = base * (1 - r * 0.06) * (1 + 0.04 * Math.sin(t * 1.3 + r));
        for (let a = 0; a <= Math.PI * 2; a += 0.03) {
          const rad =
            amp *
            (0.6 + 0.4 * Math.sin(p.k1 * a + p.ph + t)) *
            (0.75 + 0.25 * Math.cos(p.k2 * a));
          const x = cx + rad * Math.cos(a);
          const y = cy + rad * Math.sin(a);
          a === 0 ? ctx!.moveTo(x, y) : ctx!.lineTo(x, y);
        }
        ctx!.closePath();
        ctx!.stroke();
      }
      ctx!.globalAlpha = 1;
      if (animate) raf = requestAnimationFrame(frame);
    }

    // Pause the rAF loop when the tab is hidden (perf + battery).
    function onVisibility() {
      if (document.hidden) {
        running = false;
        cancelAnimationFrame(raf);
      } else if (animate) {
        running = true;
        frame();
      }
    }
    document.addEventListener("visibilitychange", onVisibility);

    frame(); // draws one static frame if !animate, else starts the loop

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [visible, animate, seed]);

  if (!visible) return null;

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 0,
        pointerEvents: "none",
        opacity: 0.16,
      }}
    />
  );
}
