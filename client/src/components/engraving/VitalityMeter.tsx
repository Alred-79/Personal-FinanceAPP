import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { useReducedMotion } from "@/hooks/useEnvironment";

/**
 * An engraved capsule gauge for a 0–1 probability — the merchant-lifecycle
 * "vitality" (probability_alive). NOT a money figure: it carries colour and a
 * mount animation, which the color law forbids on `.ledger-figures`. The fill
 * tone tracks the same credit/gold/debit law as the lifecycle stamp.
 */
function toneFor(v: number): string {
  if (v >= 0.66) return "bg-credit";
  if (v >= 0.33) return "bg-gold";
  return "bg-debit";
}

export function VitalityMeter({
  value,
  label = "Vitality",
  className,
}: {
  /** probability_alive in [0, 1]. */
  value: number;
  label?: string;
  className?: string;
}) {
  const reduce = useReducedMotion();
  const pct = Math.max(0, Math.min(1, value));
  // Draw from empty on mount (like Sparkline); skip the sweep under reduced motion.
  const [w, setW] = useState(reduce ? pct : 0);
  useEffect(() => {
    if (reduce) {
      setW(pct);
      return;
    }
    const id = requestAnimationFrame(() => setW(pct));
    return () => cancelAnimationFrame(id);
  }, [pct, reduce]);

  return (
    <div className={cn("", className)}>
      <div className="flex items-baseline justify-between">
        <span className="font-sans text-[9px] uppercase tracking-[0.18em] text-muted-foreground">
          {label}
        </span>
        <span className="font-mono text-[11px] tabular-nums text-foreground">
          {Math.round(pct * 100)}%
        </span>
      </div>
      <div className="mt-1 h-1.5 w-full overflow-hidden border border-rule-strong/30 bg-card">
        <div
          className={cn(
            "h-full transition-[width] duration-700 ease-out motion-reduce:transition-none",
            toneFor(pct)
          )}
          style={{ width: `${w * 100}%` }}
          role="meter"
          aria-valuenow={Math.round(pct * 100)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${label}: ${Math.round(pct * 100)} percent`}
        />
      </div>
    </div>
  );
}
