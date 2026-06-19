import { formatCurrency } from "@/lib/format";
import type { Earmark } from "@/types";

/**
 * W8 visual jars (reuses W7 F4 soft earmarks). Renders a goal's `progress` as a
 * single bar partitioned into the named earmark sub-buckets ("jars") plus an
 * unallocated remainder. The partitioning is the only behaviorally-validated win
 * (Soman & Cheema): it lets the user mentally account for parts of one goal
 * without ever locking liquidity — earmarks are soft and instantly reversible.
 *
 * Pure presentational: it reads the earmarks returned by `GET /goals/` (or
 * `/goals/{id}/earmarks/`) and draws the partitions. Empty earmarks → just the
 * plain progress bar (no jars), so it degrades cleanly when the flag is off.
 */

const JAR_TINTS = [
  "bg-gold/70",
  "bg-emerald-500/60",
  "bg-sky-500/60",
  "bg-violet-500/60",
  "bg-amber-500/60",
];

export function GoalJars({
  progress,
  earmarks,
  className,
}: {
  /** The goal's total saved progress, in dollars. */
  progress: number;
  earmarks: Earmark[];
  className?: string;
}) {
  const safeProgress = Math.max(progress, 0);
  const allocated = earmarks.reduce((sum, e) => sum + Math.max(e.amount, 0), 0);
  const remainder = Math.max(safeProgress - allocated, 0);
  // Width basis: never divide by zero; a goal with no progress shows an empty rail.
  const basis = safeProgress > 0 ? safeProgress : 1;

  return (
    <div className={className}>
      {/* The partitioned rail. Each jar is a labelled segment; the remainder is the
          unallocated, freely-spendable-toward-goal slice. */}
      <div
        className="flex h-3 w-full overflow-hidden rounded-full bg-muted"
        role="img"
        aria-label={`Goal partitions: ${earmarks
          .map((e) => `${e.name} ${formatCurrency(e.amount)}`)
          .join(", ")}${remainder > 0 ? `, unallocated ${formatCurrency(remainder)}` : ""}`}
      >
        {earmarks.map((e, i) => (
          <div
            key={e.id}
            className={`${JAR_TINTS[i % JAR_TINTS.length]} h-full border-r border-card/60 last:border-r-0`}
            style={{ width: `${(Math.max(e.amount, 0) / basis) * 100}%` }}
            title={`${e.name}: ${formatCurrency(e.amount)}`}
          />
        ))}
        {remainder > 0 && (
          <div
            className="h-full bg-rule-strong/20"
            style={{ width: `${(remainder / basis) * 100}%` }}
            title={`Unallocated: ${formatCurrency(remainder)}`}
          />
        )}
      </div>

      {/* The jar legend — named sub-buckets the user set aside. */}
      {earmarks.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
          {earmarks.map((e, i) => (
            <li key={e.id} className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span
                aria-hidden
                className={`inline-block h-2 w-2 rounded-sm ${JAR_TINTS[i % JAR_TINTS.length]}`}
              />
              <span className="font-medium text-foreground">{e.name}</span>
              <span className="tabular-nums">{formatCurrency(e.amount)}</span>
            </li>
          ))}
          {remainder > 0 && (
            <li className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span aria-hidden className="inline-block h-2 w-2 rounded-sm bg-rule-strong/20" />
              <span>Unallocated</span>
              <span className="tabular-nums">{formatCurrency(remainder)}</span>
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

export default GoalJars;
