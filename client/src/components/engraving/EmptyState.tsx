import { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Guilloche } from "./Guilloche";
import { Reveal, RevealItem } from "@/components/motion/Reveal";

interface EmptyStateProps {
  /** Smallcaps department line above the title, e.g. "Register · Awaiting first entry". */
  eyebrow?: string;
  /** The headline — engraved serif. */
  title: string;
  /** Supporting copy; keep it to a sentence or two. */
  description?: ReactNode;
  /** A call-to-action node (a Button, a Dialog trigger…). */
  action?: ReactNode;
  /**
   * The centred engraved motif. Defaults to a guilloché medallion; pages can
   * pass a bespoke scene (a Seal, a constellation, etc.) for their own flavour.
   */
  motif?: ReactNode;
  /** Seed so the engraving differs per surface but stays stable. */
  seed?: number;
  className?: string;
}

/**
 * A first-run / no-data showpiece — not "nothing here", but an engraved
 * certificate that doubles as onboarding. A heavy plate with a hairline gold
 * inner frame, a faint guilloché breathing behind, a centred motif, and a
 * single clear next action. Reduced-motion safe (Reveal degrades to static).
 *
 * Used wherever a surface has no data yet (Accounts, Budgets, Subscriptions,
 * Transactions, the Forecast sea-chart…). Keep the copy specific to the page.
 */
export function EmptyState({
  eyebrow,
  title,
  description,
  action,
  motif,
  seed = 7,
  className,
}: EmptyStateProps) {
  return (
    <Reveal
      className={cn(
        "col-span-full flex min-h-[44vh] items-center justify-center py-8",
        className
      )}
      gap={0.09}
    >
      <RevealItem y={20} blur={2} className="w-full max-w-xl">
        <div className="plate relative overflow-hidden bg-card px-6 py-12 text-center sm:px-12">
          {/* hairline gold inner frame — the certificate tell */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-[10px] z-[1] border border-gold/40"
          />
          {/* faint engraving breathing behind the content */}
          <div
            aria-hidden
            className="pointer-events-none absolute left-1/2 top-1/2 z-0 -translate-x-1/2 -translate-y-1/2 text-rule-strong/[0.07]"
          >
            <Guilloche size={460} rings={9} seed={seed} animate />
          </div>

          <div className="relative z-[2] flex flex-col items-center gap-4">
            {/* motif — default is a small guilloché rosette medallion */}
            <div className="text-gold/70">
              {motif ?? (
                <div className="grid place-items-center">
                  <Guilloche size={84} rings={4} seed={seed + 13} />
                </div>
              )}
            </div>

            {eyebrow && <p className="dept-label">{eyebrow}</p>}

            <h3 className="font-display text-2xl font-semibold leading-tight sm:text-3xl">
              {title}
            </h3>

            {description && (
              <p className="max-w-md font-sans text-sm leading-relaxed text-muted-foreground">
                {description}
              </p>
            )}

            {action && <div className="mt-2 flex flex-wrap justify-center gap-2">{action}</div>}
          </div>
        </div>
      </RevealItem>
    </Reveal>
  );
}
