import { ReactNode } from "react";
import { EmptyState } from "@/components/engraving/EmptyState";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

/**
 * An honest "not enough data yet" state for any model that needs density before
 * it can speak truthfully — the BG/NBD subscription-creep model (≥5 repeat
 * merchants), income smoothing (≥3 months of history), a forecast needing a
 * back-run. Instead of a broken or empty chart, it states exactly what's needed
 * and shows real progress toward the threshold. Builds on the EmptyState plate
 * so it reads as a certificate, not a dead end.
 *
 * Per docs/FRONTEND-REPOSITIONING §3 ("honest threshold states") and §6.
 */
export function ThresholdState({
  eyebrow,
  title,
  description,
  /** How many qualifying items the user has so far (e.g. repeat merchants). */
  current,
  /** How many are needed before the model engages. */
  required,
  /** Noun for the unit, e.g. "recurring charges", "months of history". */
  unit,
  action,
  seed,
  className,
}: {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  current: number;
  required: number;
  unit: string;
  action?: ReactNode;
  seed?: number;
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(current, required));
  const pct = required > 0 ? Math.round((clamped / required) * 100) : 0;
  const remaining = Math.max(0, required - clamped);

  return (
    <EmptyState
      eyebrow={eyebrow}
      title={title}
      description={
        <span className="block">
          {description}
          <span
            className={cn("mt-5 block w-full max-w-sm", description ? "" : "mt-0")}
            aria-hidden
          >
            <Progress value={pct} />
          </span>
          <span className="mt-2 flex items-baseline justify-between font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
            <span>
              <span className="text-foreground">{clamped}</span> / {required} {unit}
            </span>
            <span>
              {remaining === 0
                ? "Ready"
                : `${remaining} more to go`}
            </span>
          </span>
        </span>
      }
      action={action}
      seed={seed}
      className={className}
    />
  );
}
