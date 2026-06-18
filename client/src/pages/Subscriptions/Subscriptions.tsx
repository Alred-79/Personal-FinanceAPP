import React, { useEffect } from "react";
import { TiltCard, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Repeat } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";
import { Stamp } from "@/components/engraving/Stamp";
import { EmptyState } from "@/components/engraving/EmptyState";
import { Reveal, RevealItem } from "@/components/motion/Reveal";

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

/**
 * Standing Orders: recurring charges detected in your spending, rendered as a
 * ledger of mandates — last drawn, next due, and a running monthly burden.
 */
const Subscriptions: React.FC = () => {
  const { subscriptions, subscriptionsLoaded, fetchSubscriptions } = useStore();

  useEffect(() => {
    fetchSubscriptions();
  }, [fetchSubscriptions]);

  const monthlyTotal = subscriptions.reduce((sum, s) => {
    const perMonth =
      s.cadence === "weekly"
        ? s.amount * 4.33
        : s.cadence === "bi-weekly"
        ? s.amount * 2.17
        : s.cadence === "quarterly"
        ? s.amount / 3
        : s.cadence === "annually"
        ? s.amount / 12
        : s.amount;
    return sum + perMonth;
  }, 0);

  return (
    <>
      <PageHeader
        title="Standing Orders"
        description="Mandates drawn against your accounts on a schedule."
        reference="Folio VII · Recurring Charges"
      />

      {subscriptions.length > 0 && (
        <div className="mb-6 flex flex-wrap items-baseline justify-between gap-2 border-b border-rule-strong/30 pb-4">
          <p className="dept-label">
            {subscriptions.length} mandate{subscriptions.length === 1 ? "" : "s"} ·
            estimated monthly burden
          </p>
          <p className="intaglio text-3xl ink-debit">
            <AnimatedNumber value={monthlyTotal} />
          </p>
        </div>
      )}

      <Reveal className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:grid-cols-3">
        {subscriptions.map((s) => {
          const soon = daysUntil(s.next_date);
          return (
          <RevealItem key={s.merchant} className="h-full">
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

              <p className="intaglio text-2xl ink-debit">
                {formatCurrency(s.amount)}
              </p>

              {/* F2: lifecycle stamp (is this still alive?) + price-creep flag. */}
              {(s.lifecycle_status || s.price_change_pct != null) && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {s.lifecycle_status && LIFECYCLE[s.lifecycle_status] && (
                    <Stamp
                      variant={LIFECYCLE[s.lifecycle_status].variant}
                      still
                    >
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
              </dl>
            </CardContent>
          </TiltCard>
          </RevealItem>
          );
        })}

        {subscriptionsLoaded && subscriptions.length === 0 && (
          <EmptyState
            seed={9}
            eyebrow="Standing Orders · None on file"
            title="No standing orders detected"
            description="Mandates are spotted automatically from your transaction history once you've linked an account and built up a few months of spending."
          />
        )}
      </Reveal>
    </>
  );
};

export default Subscriptions;
