import { X } from "lucide-react";
import type { Goal } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { Button } from "@/components/ui/button";

const BAND_VARS = ["--chart-1", "--chart-2", "--chart-4", "--chart-5", "--chart-6"];

/**
 * The DOM detail card for the focused vessel — overlaid on the canvas. All money
 * is clean DOM here (Figure rows), never painted in 3D. Drives the same CRUD
 * handlers as the 2D fallback, so edit/deposit/what-if behave identically.
 */
export function ReliquaryFocusPanel({
  goal,
  onClose,
  onEdit,
  onDeposit,
  onWhatIf,
}: {
  goal: Goal;
  onClose: () => void;
  onEdit: (g: Goal) => void;
  onDeposit: (g: Goal) => void;
  onWhatIf: (g: Goal) => void;
}) {
  const earmarks = goal.earmarks ?? [];
  const allocated = earmarks.reduce((s, e) => s + e.amount, 0);
  const unallocated = Math.max(0, (goal.progress ?? 0) - allocated);
  const pct =
    goal.amount > 0 ? Math.round(((goal.progress ?? 0) / goal.amount) * 100) : 0;

  return (
    <div className="pointer-events-auto absolute inset-x-3 bottom-3 mx-auto max-w-md animate-rise-in border border-rule-strong/40 bg-card/95 p-5 shadow-plate backdrop-blur sm:inset-x-auto sm:left-1/2 sm:w-[28rem] sm:-translate-x-1/2">
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute right-2 top-2 grid h-7 w-7 place-items-center text-muted-foreground transition-colors hover:text-foreground"
      >
        <X size={15} />
      </button>

      <p className="dept-label">Certificate of Savings</p>
      <h3 className="font-display text-xl font-semibold leading-tight">
        {goal.name}
      </h3>

      <div className="mt-2 flex items-baseline gap-2">
        <span className="intaglio text-2xl text-foreground">
          {formatCurrency(goal.progress ?? 0)}
        </span>
        <span className="ledger-figures text-xs text-muted-foreground">
          of {formatCurrency(goal.amount)} · {pct}%
        </span>
      </div>

      {(earmarks.length > 0 || unallocated > 0) && (
        <div className="mt-4 space-y-1.5 border-t border-rule pt-3">
          <p className="dept-label mb-1">Earmarks</p>
          {earmarks.map((e, i) => (
            <div key={e.id} className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-2">
                <span
                  className="h-2.5 w-2.5 shrink-0"
                  style={{ background: `hsl(var(${BAND_VARS[i % BAND_VARS.length]}))` }}
                  aria-hidden
                />
                <span className="truncate font-sans text-sm">{e.name}</span>
              </span>
              <span className="font-mono text-sm tabular-nums text-foreground">
                {formatCurrency(e.amount)}
              </span>
            </div>
          ))}
          {unallocated > 0 && (
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2">
                <span
                  className="h-2.5 w-2.5 shrink-0"
                  style={{ background: "hsl(var(--credit))" }}
                  aria-hidden
                />
                <span className="font-sans text-sm text-muted-foreground">
                  Unallocated
                </span>
              </span>
              <span className="font-mono text-sm tabular-nums text-muted-foreground">
                {formatCurrency(unallocated)}
              </span>
            </div>
          )}
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <Button size="sm" onClick={() => onDeposit(goal)}>
          Deposit
        </Button>
        <Button size="sm" variant="outline" onClick={() => onWhatIf(goal)}>
          What if…
        </Button>
        <Button size="sm" variant="outline" onClick={() => onEdit(goal)}>
          Edit
        </Button>
      </div>
    </div>
  );
}
