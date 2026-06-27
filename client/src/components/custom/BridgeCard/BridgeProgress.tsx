import { cn } from "@/lib/utils";

export type BridgeStage = "propose" | "recorded" | "done";

const STEPS: { key: BridgeStage; label: string }[] = [
  { key: "propose", label: "Drafted" },
  { key: "recorded", label: "You do it" },
  { key: "done", label: "Verified" },
];

const ORDER: Record<BridgeStage, number> = { propose: 0, recorded: 1, done: 2 };

/**
 * The honest three-state Bridge chip — Drafted → You do it → Verified ✓ —
 * mirroring the real lifecycle (proposed/acknowledged → your bank action →
 * verified by your own sync). Making the verified-by-your-own-bank-data step
 * visible is the credibility win: the app never claims it moved the money, only
 * that it watched your bank confirm it. Per docs/FRONTEND-REPOSITIONING §4.
 */
export function BridgeProgress({ stage }: { stage: BridgeStage }) {
  const active = ORDER[stage];
  return (
    <ol
      className="flex items-center gap-1.5"
      aria-label={`Action progress: ${STEPS[active].label}`}
    >
      {STEPS.map((step, i) => {
        const done = i < active;
        const current = i === active;
        return (
          <li key={step.key} className="flex items-center gap-1.5">
            <span
              className={cn(
                "inline-flex items-center gap-1 font-mono text-[10px] font-medium uppercase tracking-[0.14em] transition-colors",
                current && "text-gold",
                done && "text-muted-foreground",
                !current && !done && "text-muted-foreground/45",
              )}
              aria-current={current ? "step" : undefined}
            >
              <span
                aria-hidden
                className={cn(
                  "grid h-3.5 w-3.5 place-items-center rounded-full border text-[8px] leading-none",
                  current && "border-gold bg-gold/15 text-gold",
                  done && "border-credit/60 bg-credit/10 text-credit",
                  !current && !done && "border-rule-strong/40 text-transparent",
                )}
              >
                {done ? "✓" : i + 1}
              </span>
              {step.label}
            </span>
            {i < STEPS.length - 1 && (
              <span
                aria-hidden
                className={cn(
                  "h-px w-4 transition-colors",
                  i < active ? "bg-credit/50" : "bg-rule-strong/30",
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
