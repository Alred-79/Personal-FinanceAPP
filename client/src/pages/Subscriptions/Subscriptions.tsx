import React, { useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import PageHeader from "@/components/layout/PageHeader";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";

const formatDate = (iso: string | null) =>
  iso
    ? new Date(iso + "T00:00:00").toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : "—";

/**
 * Subscriptions view: recurring charges we spot in your spending,
 * with the last and next charge dates and a gentle "cancel?" nudge.
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
        title="Subscriptions"
        description={
          subscriptions.length > 0
            ? `Estimated ${formatCurrency(monthlyTotal)} / month across ${
                subscriptions.length
              } subscription${subscriptions.length === 1 ? "" : "s"}.`
            : "Recurring charges detected from your spending."
        }
      />

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:grid-cols-3">
        {subscriptions.map((s) => (
          <Card key={s.merchant} className="relative">
            <CardContent className="pt-6">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-xl font-semibold">{s.title}</h2>
                <Badge variant="secondary">{s.cadence}</Badge>
              </div>
              <p className="text-2xl font-bold">{formatCurrency(s.amount)}</p>
              <p className="mt-2 text-sm text-muted-foreground">
                Last charge: {formatDate(s.last_date)}
              </p>
              <p className="text-sm text-muted-foreground">
                Next charge: {formatDate(s.next_date)}
              </p>
              <p className="mt-3 text-xs text-muted-foreground">
                Seen {s.occurrences} times.
              </p>
            </CardContent>
          </Card>
        ))}

        {subscriptionsLoaded && subscriptions.length === 0 && (
          <div className="col-span-full flex min-h-[40vh] flex-col items-center justify-center gap-3">
            <p className="font-mono text-sm text-muted-foreground text-center max-w-sm">
              No recurring charges detected yet.
            </p>
            <p className="font-mono text-xs text-muted-foreground/60 text-center max-w-sm">
              Subscriptions are auto-detected from your transaction history once you've linked an account and have a few months of spending data.
            </p>
          </div>
        )}
      </div>
    </>
  );
};

export default Subscriptions;
