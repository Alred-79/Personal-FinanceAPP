import { useEffect, useRef } from "react";
import { useReducedMotion } from "@/hooks/useEnvironment";

/**
 * GoldDust — subtle drifting gold specks ("ink dust") over the page for
 * atmosphere. Canvas 2D, deterministic-ish drift, very low density so it reads
 * as fine grain rather than a snow effect. Behind content, aria-hidden, paused
 * on hidden tab, off under reduced motion. Color law: pure chrome.
 */
export function GoldDust({ count = 60, opacity = 0.5 }: { count?: number; opacity?: number }) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (reduce) return;
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const DPR = Math.min(window.devicePixelRatio || 1, 2);
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

    const gold = () =>
      getComputedStyle(document.documentElement).getPropertyValue("--gold").trim();

    type P = { x: number; y: number; r: number; vx: number; vy: number; tw: number };
    const parts: P[] = Array.from({ length: count }, () => ({
      x: Math.random() * W,
      y: Math.random() * H,
      r: (0.6 + Math.random() * 1.6) * DPR,
      vx: (Math.random() - 0.5) * 0.12 * DPR,
      vy: (-0.05 - Math.random() * 0.12) * DPR, // gentle upward drift
      tw: Math.random() * Math.PI * 2, // twinkle phase
    }));

    let raf = 0;
    let running = true;
    let t = 0;
    function frame() {
      if (!running) return;
      t += 0.02;
      ctx!.clearRect(0, 0, W, H);
      const g = gold();
      for (const p of parts) {
        p.x += p.vx;
        p.y += p.vy;
        if (p.y < -5) { p.y = H + 5; p.x = Math.random() * W; }
        if (p.x < -5) p.x = W + 5;
        if (p.x > W + 5) p.x = -5;
        const tw = 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(t + p.tw));
        ctx!.globalAlpha = tw * opacity;
        ctx!.fillStyle = `hsl(${g})`;
        ctx!.beginPath();
        ctx!.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx!.fill();
      }
      ctx!.globalAlpha = 1;
      raf = requestAnimationFrame(frame);
    }
    function onVisibility() {
      if (document.hidden) { running = false; cancelAnimationFrame(raf); }
      else { running = true; frame(); }
    }
    document.addEventListener("visibilitychange", onVisibility);
    frame();

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [reduce, count, opacity]);

  if (reduce) return null;
  return (
    <canvas
      ref={ref}
      aria-hidden="true"
      style={{ position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none" }}
    />
  );
}
