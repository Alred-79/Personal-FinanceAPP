import React, { useEffect } from "react";
import { useStore } from "@/store/store";
import { formatCurrency, categoryColor } from "@/lib/format";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";
import { EmptyState } from "@/components/engraving/EmptyState";
import { SectionRule } from "@/components/engraving/SectionRule";
import { Reveal, RevealItem } from "@/components/motion/Reveal";
import { groupByMonth, next90Total } from "@/lib/cadence";

const dayLabel = (iso: string) =>
  new Date(iso + "T00:00:00").toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });

/** Whole days from today until an ISO date (null if past / absent). */
const daysUntil = (iso: string): number | null => {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.ceil(
    (new Date(iso + "T00:00:00").getTime() - today.getTime()) / 86_400_000
  );
  return diff >= 0 ? diff : null;
};

/**
 * A forward agenda of upcoming recurring charges — the temporal complement to
 * the standing-orders register. Reads the already-fetched projection slice, so
 * it can be dropped anywhere (Subscriptions tab today, the Almanac later).
 */
const CadenceCalendar: React.FC = () => {
  const { projectedTransactions, projectedLoaded, fetchProjectedTransactions } =
    useStore();

  useEffect(() => {
    fetchProjectedTransactions();
  }, [fetchProjectedTransactions]);

  const months = groupByMonth(projectedTransactions);
  const total = next90Total(projectedTransactions);

  if (projectedLoaded && projectedTransactions.length === 0) {
    return (
      <Reveal className="grid grid-cols-1">
        <EmptyState
          seed={7}
          eyebrow="Cadence · Nothing scheduled"
          title="No standing orders project ahead"
          description="Once recurring charges are detected, the next three months of obligations are charted here so nothing draws against you by surprise."
        />
      </Reveal>
    );
  }

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-baseline justify-between gap-2 border-b border-rule-strong/30 pb-4">
        <p className="dept-label">Projected obligations · next 90 days</p>
        <p className="intaglio text-3xl ink-debit">
          <AnimatedNumber value={total} />
        </p>
      </div>

      <Reveal className="space-y-10">
        {months.map((m) => (
          <RevealItem key={m.key}>
            <div className="mb-3 flex items-baseline justify-between gap-3">
              <SectionRule className="!justify-start">{m.label}</SectionRule>
              <p className="ledger-figures shrink-0 text-sm ink-debit">
                {formatCurrency(m.subtotal)}
              </p>
            </div>

            <ul className="relative ml-1 space-y-2 border-l border-rule-strong/30 pl-5">
              {m.rows.map((r) => {
                const soon = daysUntil(r.date);
                return (
                  <li
                    key={r.id}
                    className="relative flex items-center justify-between gap-3"
                  >
                    {/* node on the engraved rail */}
                    <span className="absolute -left-[1.45rem] top-1.5 h-2 w-2 rounded-full border border-card bg-gold" />
                    <div className="flex min-w-0 items-center gap-2.5">
                      <span
                        className="h-2.5 w-2.5 shrink-0 rounded-full"
                        style={{ background: categoryColor(r.category) }}
                        aria-hidden="true"
                      />
                      <span className="truncate font-display text-sm">
                        {r.title}
                      </span>
                      <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                        {dayLabel(r.date)}
                      </span>
                      {soon != null && soon <= 7 && (
                        <span className="shrink-0 rounded-none bg-gold/15 px-1 py-px text-[9px] font-semibold uppercase tracking-wide text-gold">
                          {soon === 0 ? "today" : `in ${soon}d`}
                        </span>
                      )}
                    </div>
                    <span className="shrink-0 font-mono text-sm tabular-nums ink-debit">
                      {formatCurrency(r.amount)}
                    </span>
                  </li>
                );
              })}
            </ul>
          </RevealItem>
        ))}
      </Reveal>
    </div>
  );
};

export default CadenceCalendar;
