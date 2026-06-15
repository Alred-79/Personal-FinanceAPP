import { useEffect, useRef } from "react";
import { useFlags } from "@/store/gameMode";
import { useReducedMotion, usePointerFine } from "@/hooks/useEnvironment";

/**
 * BurinCursor — the cursor becomes an engraver's burin that leaves a fading
 * gold ink trail; over interactive elements it morphs into a pointing manicule.
 *
 * Gating (a11y-critical): only when flags.burin (ambient+) AND a real fine
 * pointer AND not reduce-motion. Otherwise it renders nothing and the native
 * cursor is used. The native caret is preserved over text inputs (the global
 * `cursor:none` on body is only set while this is active — see the effect).
 *
 * One global instance (mounted in AppShell). The nib + ink canvas sit above the
 * page (z above content) but are pointer-events:none so they never trap input.
 */
const INTERACTIVE = "button,a,input,textarea,select,[role='button'],[role='option'],label,.plate-tilt";

export function BurinCursor() {
  const flags = useFlags();
  const reduce = useReducedMotion();
  const fine = usePointerFine();
  const active = flags.burin && fine && !reduce;

  const nibRef = useRef<SVGSVGElement | null>(null);
  const inkRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (!active) return;
    const nib = nibRef.current;
    const ink = inkRef.current;
    if (!nib || !ink) return;
    const ctx = ink.getContext("2d");
    if (!ctx) return;

    // Hide the system cursor app-wide while the burin is active; restore on cleanup.
    const prevCursor = document.body.style.cursor;
    document.body.style.cursor = "none";

    const DPR = Math.min(window.devicePixelRatio || 1, 2);
    let W = 0;
    let H = 0;
    function resize() {
      W = ink!.width = Math.floor(window.innerWidth * DPR);
      H = ink!.height = Math.floor(window.innerHeight * DPR);
      ink!.style.width = window.innerWidth + "px";
      ink!.style.height = window.innerHeight + "px";
    }
    resize();
    window.addEventListener("resize", resize);

    const gold = () =>
      `hsl(${getComputedStyle(document.documentElement).getPropertyValue("--gold").trim()})`;

    let px: number | null = null;
    let py: number | null = null;

    function onMove(e: PointerEvent) {
      nib!.style.transform = `translate(${e.clientX - 3}px, ${e.clientY - 2}px)`;
      const overTarget =
        e.target instanceof Element && !!e.target.closest(INTERACTIVE);
      nib!.classList.toggle("over-target", overTarget);
      if (px != null && py != null) {
        ctx!.strokeStyle = gold();
        ctx!.lineWidth = DPR * 1.1;
        ctx!.lineCap = "round";
        ctx!.globalAlpha = 0.5;
        ctx!.beginPath();
        ctx!.moveTo(px * DPR, py * DPR);
        ctx!.lineTo(e.clientX * DPR, e.clientY * DPR);
        ctx!.stroke();
        ctx!.globalAlpha = 1;
      }
      px = e.clientX;
      py = e.clientY;
    }
    function onDown(e: PointerEvent) {
      ctx!.fillStyle = gold();
      ctx!.globalAlpha = 0.6;
      ctx!.beginPath();
      ctx!.arc(e.clientX * DPR, e.clientY * DPR, 3 * DPR, 0, Math.PI * 2);
      ctx!.fill();
      ctx!.globalAlpha = 1;
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerdown", onDown);

    // Fade the trail every frame (paint a faint clearing veil).
    let raf = 0;
    let running = true;
    function fade() {
      if (!running) return;
      ctx!.globalCompositeOperation = "destination-out";
      ctx!.fillStyle = "rgba(0,0,0,0.06)";
      ctx!.fillRect(0, 0, W, H);
      ctx!.globalCompositeOperation = "source-over";
      raf = requestAnimationFrame(fade);
    }
    function onVisibility() {
      if (document.hidden) {
        running = false;
        cancelAnimationFrame(raf);
      } else {
        running = true;
        fade();
      }
    }
    document.addEventListener("visibilitychange", onVisibility);
    fade();

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      document.body.style.cursor = prevCursor;
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerdown", onDown);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [active]);

  if (!active) return null;

  return (
    <>
      <canvas
        ref={inkRef}
        aria-hidden="true"
        style={{
          position: "fixed",
          inset: 0,
          zIndex: "var(--z-ink)" as unknown as number,
          pointerEvents: "none",
        }}
      />
      <svg
        ref={nibRef}
        viewBox="0 0 26 26"
        aria-hidden="true"
        className="burin-nib"
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          width: 26,
          height: 26,
          pointerEvents: "none",
          zIndex: "var(--z-nib)" as unknown as number,
        }}
      >
        <g
          className="g-burin"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.4}
          strokeLinejoin="round"
        >
          <path d="M3 23 L9 17 L13 21 L7 27 Z" transform="translate(0,-4)" />
          <path
            d="M9 17 L20 6 a2 2 0 0 1 3 3 L12 20 Z"
            transform="translate(0,-4)"
            fill="currentColor"
            fillOpacity={0.15}
          />
        </g>
        <g
          className="g-manicule"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.2}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path
            d="M4 14 q-1 -3 2 -3 q1 -3 3 -2 q0 -4 3 -3 q1 -4 3 -2 l0 6 q3 -2 5 0 q2 1 1 4 q-1 5 -5 7 q-4 2 -8 -1 q-3 -2 -4 -6 q-1 -2 1 -3 q1 0 2 2"
            fill="currentColor"
            fillOpacity={0.12}
          />
        </g>
      </svg>
    </>
  );
}
