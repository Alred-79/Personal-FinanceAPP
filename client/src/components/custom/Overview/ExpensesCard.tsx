import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { useNavigate } from "react-router-dom";
import { Stamp } from "@/components/engraving/Stamp";

/**
 * Budget status drawn as a column of envelopes: each category a ruled row with
 * a fill bar showing spent vs. effective limit, overspends stamped in red ink.
 */
export default function ExpensesCard() {
  const { budgets } = useStore();
  const navigate = useNavigate();

  if (budgets.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Budget Status</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col items-start gap-3 py-6">
          <p className="font-sans text-sm italic text-muted-foreground">
            No budget envelopes have been ruled yet.
          </p>
          <button
            onClick={() => navigate("/budgets")}
            className="press border border-rule-strong/60 bg-card px-3 py-1.5 font-sans text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground shadow-plate transition-all hover:bg-wash"
          >
            + Rule a budget
          </button>
        </CardContent>
      </Card>
    );
  }

  const rows = [...budgets].sort((a, b) => b.spent / Math.max(1, b.effective_limit) - a.spent / Math.max(1, a.effective_limit));

  return (
    <Card raking>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle>Budget Status</CardTitle>
        <button
          onClick={() => navigate("/budgets")}
          className="font-sans text-[10px] uppercase tracking-[0.18em] text-muted-foreground transition-colors hover:text-gold"
        >
          View all →
        </button>
      </CardHeader>
      <CardContent className="space-y-3">
        {rows.slice(0, 6).map((b) => {
          const pct = Math.min(
            100,
            (b.spent / Math.max(1, b.effective_limit)) * 100
          );
          const accent = b.over_budget
            ? "hsl(var(--debit))"
            : b.on_pace
            ? "hsl(var(--credit))"
            : "hsl(var(--gold))";
          return (
            <div key={b.id} className="space-y-1">
              <div className="flex items-baseline justify-between gap-2">
                <span className="flex items-center gap-2 font-sans text-[13px] text-foreground">
                  {b.category}
                  {b.over_budget && (
                    <Stamp variant="debit" still>
                      Over
                    </Stamp>
                  )}
                </span>
                <span className="ledger-figures text-xs text-muted-foreground">
                  <span className="text-foreground">{formatCurrency(b.spent)}</span>
                  {" / "}
                  {formatCurrency(b.effective_limit)}
                </span>
              </div>
              <div className="relative h-2 w-full overflow-hidden border border-rule-strong/40 bg-secondary">
                <div
                  className="absolute inset-y-0 left-0 transition-[width] duration-700 ease-out"
                  style={{ width: `${pct}%`, background: accent }}
                />
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
