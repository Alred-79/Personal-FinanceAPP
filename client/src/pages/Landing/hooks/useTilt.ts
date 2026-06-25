import { useRef, type MouseEvent as ReactMouseEvent } from "react";
import { usePointerFine, useReducedMotion } from "@/hooks/useEnvironment";

/**
 * Cursor-tracking 3D tilt for a card. Writes --rx/--ry (perspective rotation) and
 * --mx/--my (a 0–100% pointer position for sheen) onto the element; the CSS does
 * the rest, including lifting Z-layered children so they "pop" off the page.
 * Pure CSS-var writes (no React state / motion values) so it stays cheap and
 * can't fight the filmstrip's scroll transform. Inert on touch / reduced motion.
 */
export function useTilt(max = 9) {
  const fine = usePointerFine();
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const enabled = fine && !reduce;

  const onMove = (e: ReactMouseEvent) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5;
    const py = (e.clientY - r.top) / r.height - 0.5;
    el.style.setProperty("--ry", `${px * max}deg`);
    el.style.setProperty("--rx", `${-py * max}deg`);
    el.style.setProperty("--mx", `${(px + 0.5) * 100}%`);
    el.style.setProperty("--my", `${(py + 0.5) * 100}%`);
  };

  const reset = () => {
    const el = ref.current;
    if (!el) return;
    el.style.setProperty("--rx", "0deg");
    el.style.setProperty("--ry", "0deg");
  };

  return {
    ref,
    enabled,
    handlers: enabled ? { onMouseMove: onMove, onMouseLeave: reset } : {},
  };
}
