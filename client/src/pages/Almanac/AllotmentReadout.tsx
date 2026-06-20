import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { Figure } from "@/components/engraving/Figure";

/**
 * The paycheck-allotment readout: how much of this period's discretionary
 * ceiling (a fixed % of the latest paycheck) has been spent. The bar is an
 * engraved meter — not a money figure — so it may carry colour; the dollar
 * amounts beside it stay clean DOM.
 */
export default function AllotmentReadout() {
  const ceiling = useStore((s) => s.budgetAllotment);
  const spent = useStore((s) => s.spendOverTime);
  const hasLoaded = useStore((s) => s.hasLoaded);

  if (!hasLoaded) {
    return (
      <p className="font-mono text-sm text-muted-foreground">
        Gathering this period's figures…
      </p>
    );
  }

  const pct = ceiling > 0 ? Math.min(1, spent / ceiling) : 0;
  const over = spent > ceiling;
  const remaining = ceiling - spent;

  return (
    <div className="space-y-6">
      <div className="border border-rule-strong/20 bg-card p-6">
        <div className="flex items-baseline justify-between">
          <p className="dept-label">Paycheck allotment</p>
          <p className="font-mono text-sm tabular-nums text-muted-foreground">
            {Math.round(pct * 100)}% spent
          </p>
        </div>
        <div className="relative mt-3 h-3 w-full overflow-hidden border border-rule-strong/30 bg-background">
          <div
            className={`h-full transition-[width] duration-700 ease-out motion-reduce:transition-none ${
              over ? "bg-debit" : "bg-gold"
            }`}
            style={{ width: `${pct * 100}%` }}
            role="meter"
            aria-valuenow={Math.round(pct * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Share of paycheck allotment spent"
          />
        </div>
        {over && (
          <p className="mt-2 font-sans text-xs text-debit">
            Over this period's allotment by {formatCurrency(spent - ceiling)}.
          </p>
        )}
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Figure label="Allotment ceiling" value={formatCurrency(ceiling)} />
        <Figure label="Spent" value={formatCurrency(spent)} accent="debit" />
        <Figure
          label="Remaining"
          value={formatCurrency(Math.max(0, remaining))}
          accent={over ? "debit" : "credit"}
        />
      </div>
    </div>
  );
}
