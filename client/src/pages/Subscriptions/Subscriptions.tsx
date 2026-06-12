import React, { useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Repeat } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";

const formatDate = (iso: string | null) =>
  iso
    ? new Date(iso + "T00:00:00").toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : "—";

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

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:grid-cols-3">
        {subscriptions.map((s, i) => (
          <Card
            key={s.merchant}
            className="relative animate-rise-in"
            style={{ animationDelay: `${i * 50}ms` }}
          >
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

              <dl className="mt-4 space-y-1.5 border-t border-rule pt-3 font-mono text-[11px]">
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Last drawn</dt>
                  <dd className="text-foreground">{formatDate(s.last_date)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Next due</dt>
                  <dd className="text-gold">{formatDate(s.next_date)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Observed</dt>
                  <dd className="text-muted-foreground">{s.occurrences}×</dd>
                </div>
              </dl>
            </CardContent>
          </Card>
        ))}

        {subscriptionsLoaded && subscriptions.length === 0 && (
          <div className="col-span-full flex min-h-[40vh] flex-col items-center justify-center gap-3 text-center">
            <p className="font-display text-2xl text-muted-foreground">
              No standing orders detected
            </p>
            <p className="max-w-sm font-sans text-sm italic text-muted-foreground">
              Mandates are spotted automatically from your transaction history
              once you've linked an account and built up a few months of spending.
            </p>
          </div>
        )}
      </div>
    </>
  );
};

export default Subscriptions;
