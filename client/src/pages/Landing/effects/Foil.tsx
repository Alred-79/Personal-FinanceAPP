import { ReactNode, useEffect, useRef } from "react";
import { usePointerFine, useReducedMotion } from "@/hooks/useEnvironment";
import { cn } from "@/lib/utils";

/**
 * Holographic foil — an iridescent sheen that shifts hue and position with the
 * pointer, like the optically-variable foil / security thread on a banknote. The
 * sheen is a separate overlay layer, so it decorates SHAPES and RIBBONS only,
 * never body text (gradient text is banned). Reacts on fine pointers; static
 * (a faint fixed sheen) under reduced motion or on touch.
 */
export function Foil({ className, children }: { className?: string; children?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const fine = usePointerFine();
  const reduce = useReducedMotion();

  useEffect(() => {
    const el = ref.current;
    if (!el || !fine || reduce) return;
    const onMove = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width;
      const y = (e.clientY - r.top) / r.height;
      el.style.setProperty("--fx", String(Math.max(-0.4, Math.min(1.4, x))));
      el.style.setProperty("--fy", String(Math.max(-0.4, Math.min(1.4, y))));
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, [fine, reduce]);

  return (
    <div ref={ref} className={cn("foil", className)}>
      {children}
      <span aria-hidden className={cn("foil__sheen", reduce && "foil__sheen--static")} />
    </div>
  );
}
