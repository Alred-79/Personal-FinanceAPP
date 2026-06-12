import { useEffect, useRef, useState } from "react";

interface AnimatedNumberProps {
  value: number;
  /** Formats the in-flight value for display. Defaults to 2-dp currency. */
  format?: (n: number) => string;
  /** Animation length in ms. */
  duration?: number;
  className?: string;
}

const defaultFormat = (n: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(n);

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * A figure that counts up like a mechanical register. Animates from the
 * previously shown value on change; honours prefers-reduced-motion.
 */
export function AnimatedNumber({
  value,
  format = defaultFormat,
  duration = 900,
  className,
}: AnimatedNumberProps) {
  const [shown, setShown] = useState(value);
  const fromRef = useRef(value);
  const frameRef = useRef<number>();

  useEffect(() => {
    if (prefersReducedMotion() || duration <= 0) {
      fromRef.current = value;
      setShown(value);
      return;
    }
    const from = fromRef.current;
    if (from === value) return;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
      setShown(from + (value - from) * eased);
      if (t < 1) {
        frameRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = value;
      }
    };
    frameRef.current = requestAnimationFrame(tick);
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
      fromRef.current = value;
    };
  }, [value, duration]);

  return (
    <span className={className} aria-live="polite">
      {format(shown)}
    </span>
  );
}
