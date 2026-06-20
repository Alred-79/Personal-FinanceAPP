import { Seal } from "@/components/engraving/Seal";
import { formatCurrency } from "@/lib/format";
import type { TaxSummary } from "@/types";

const prettyDate = (iso: string) =>
  new Date(iso + "T00:00:00").toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });

/**
 * The estimated quarterly payments as four engraved plates — each with its due
 * date and per-quarter figure, a wax Seal on quarters already covered by
 * payments, the next-due quarter ringed in gold, and overdue quarters in debit.
 * Pure read over the summary's existing fields.
 */
export function QuarterlyCalendar({
  quarterly,
}: {
  quarterly: TaxSummary["estimated_quarterly"];
}) {
  const perQ = quarterly.safe_harbor_per_quarter ?? quarterly.per_quarter;
  const paid = quarterly.payments_made;
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  // Quarters fully covered by payments_made, in order (cumulative).
  const coveredCount =
    perQ > 0 ? Math.floor(paid / perQ) : 0;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {quarterly.due_dates.map(([q, d], i) => {
        const covered = i < coveredCount;
        const due = new Date(d + "T00:00:00");
        const overdue = !covered && due < today;
        const isNext = !covered && !overdue && i === coveredCount;
        const tone = overdue
          ? "border-debit/50"
          : isNext
          ? "border-gold/60"
          : "border-rule-strong/30";
        return (
          <div key={q} className={`relative border ${tone} bg-card p-3`}>
            {covered && (
              <span className="absolute right-1.5 top-1.5">
                <Seal label="Paid · Paid" size={26} tone="approved" />
              </span>
            )}
            <p className="dept-label">{q}</p>
            <p className="font-mono text-[11px] text-muted-foreground">
              {prettyDate(d)}
            </p>
            <p className="ledger-figures mt-1 text-sm tabular-nums">
              {formatCurrency(perQ)}
            </p>
            <p
              className={`mt-1 font-sans text-[10px] uppercase tracking-[0.12em] ${
                overdue
                  ? "text-debit"
                  : covered
                  ? "text-credit"
                  : isNext
                  ? "text-gold"
                  : "text-muted-foreground"
              }`}
            >
              {covered ? "Paid" : overdue ? "Overdue" : isNext ? "Next due" : "Upcoming"}
            </p>
          </div>
        );
      })}
    </div>
  );
}
