import React from "react";
import { TiltCard, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Repeat } from "lucide-react";
import { Subscription } from "@/types";
import { formatCurrency } from "@/lib/format";
import { Stamp } from "@/components/engraving/Stamp";
import { VitalityMeter } from "@/components/engraving/VitalityMeter";
import { projectedAnnual } from "@/lib/subscriptions";

// F2: lifecycle status → stamp wording + variant (color law: credit=fine,
// gold=attention, debit=likely dead). Only shown when the model has an opinion.
const LIFECYCLE: Record<
  string,
  { text: string; variant: "credit" | "gold" | "debit" }
> = {
  active: { text: "Likely active", variant: "credit" },
  lapsing: { text: "May have lapsed", variant: "gold" },
  dormant: { text: "Dormant", variant: "debit" },
};

const formatDate = (iso: string | null) =>
  iso
    ? new Date(iso + "T00:00:00").toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : "—";

/** Whole days from today until an ISO date (null if no date / in the past). */
const daysUntil = (iso: string | null): number | null => {
  if (!iso) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(iso + "T00:00:00");
  const diff = Math.ceil((target.getTime() - today.getTime()) / 86_400_000);
  return diff >= 0 ? diff : null;
};

/** One standing-order mandate, with optional F2 lifecycle enrichment. */
const SubscriptionCard: React.FC<{ sub: Subscription }> = ({ sub: s }) => {
  const soon = daysUntil(s.next_date);
  const annual = projectedAnnual(s);
  const expected =
    s.expected_purchases != null ? Math.round(s.expected_purchases) : null;

  return (
    <TiltCard className="relative h-full">
      <CardContent className="p-6">
        <div className="mb-3 flex items-start justify-between gap-2">
          <div className="flex items-center gap-3">
            <span className="grid h-9 w-9 shrink-0 place-items-center border border-rule-strong/40 bg-card text-gold">
              <Repeat className="h-[18px] w-[18px]" />
            </span>
            <h2 className="font-display text-lg font-semibold leading-tight">
              {s.title}
            </h2>
          </div>
          <Badge variant="secondary">{s.cadence}</Badge>
        </div>

        <p className="intaglio text-2xl ink-debit">{formatCurrency(s.amount)}</p>

        {/* F2: lifecycle stamp (is this still alive?) + price-creep flag. */}
        {(s.lifecycle_status || (s.price_change_pct ?? 0) > 0) && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {s.lifecycle_status && LIFECYCLE[s.lifecycle_status] && (
              <Stamp variant={LIFECYCLE[s.lifecycle_status].variant} still>
                {LIFECYCLE[s.lifecycle_status].text}
              </Stamp>
            )}
            {s.price_change_pct != null && s.price_change_pct > 0 && (
              <span
                className="rounded-none bg-debit/10 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-debit"
                title={
                  s.prev_amount != null
                    ? `was ${formatCurrency(s.prev_amount)}`
                    : undefined
                }
              >
                ↑ {Math.round(s.price_change_pct * 100)}% price
              </span>
            )}
          </div>
        )}

        {/* F2: vitality gauge (probability_alive) + expected upcoming charges. */}
        {s.probability_alive != null && (
          <div className="mt-4">
            <VitalityMeter value={s.probability_alive} />
            {expected != null && (
              <p className="mt-1.5 font-mono text-[10px] text-muted-foreground">
                ~{expected} more {expected === 1 ? "charge" : "charges"} expected
              </p>
            )}
          </div>
        )}

        <dl className="mt-4 space-y-1.5 border-t border-rule pt-3 font-mono text-[11px]">
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Last drawn</dt>
            <dd className="text-foreground">{formatDate(s.last_date)}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Next due</dt>
            <dd className="flex items-center gap-1.5 text-gold">
              {soon != null && soon <= 7 && (
                <span
                  className="rounded-none bg-gold/15 px-1 py-px text-[9px] font-semibold uppercase tracking-wide text-gold"
                  title="Charge expected within a week"
                >
                  {soon === 0 ? "today" : `in ${soon}d`}
                </span>
              )}
              {formatDate(s.next_date)}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Observed</dt>
            <dd className="text-muted-foreground">{s.occurrences}×</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Projected / yr</dt>
            <dd
              className="ink-debit"
              title={
                (s.price_change_pct ?? 0) > 0
                  ? "Projected at the new, higher rate"
                  : undefined
              }
            >
              {formatCurrency(annual)}
            </dd>
          </div>
        </dl>
      </CardContent>
    </TiltCard>
  );
};

export default SubscriptionCard;
