import { useEffect } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useStore } from "@/store/store";
import { formatCurrency, categoryColor } from "@/lib/format";
import { Sparkline } from "@/components/engraving/Sparkline";
import { EmptyState } from "@/components/engraving/EmptyState";
import { buildHeatGrid, bucketLabel } from "@/lib/almanac";
import { useReducedMotion } from "@/hooks/useEnvironment";
import type { AnalyticsParams } from "@/types";

/**
 * The Spending Atlas: the category × time pivot from /analytics/spending,
 * rendered as an engraved heat-grid. Cell ink is the category colour at a
 * column-normalised alpha (so a quiet category still reads against a loud one);
 * the row Σ and per-bucket totals are clean money figures.
 */
export default function AlmanacHeatGrid() {
  const analytics = useStore((s) => s.analytics);
  const analyticsLoaded = useStore((s) => s.analyticsLoaded);
  const analyticsParams = useStore((s) => s.analyticsParams);
  const fetchAnalytics = useStore((s) => s.fetchAnalytics);
  const reduce = useReducedMotion();

  useEffect(() => {
    fetchAnalytics(analyticsParams);
    // Initial load only; control changes refetch via the selects.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchAnalytics]);

  const setParam = (patch: Partial<AnalyticsParams>) =>
    fetchAnalytics({ ...analyticsParams, ...patch });

  const Controls = (
    <div className="mb-5 flex flex-wrap items-center gap-3">
      <Select
        value={analyticsParams.tx_type}
        onValueChange={(v) => setParam({ tx_type: v as "expense" | "income" })}
      >
        <SelectTrigger className="w-32" aria-label="Flow">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="expense">Spending</SelectItem>
          <SelectItem value="income">Income</SelectItem>
        </SelectContent>
      </Select>
      <Select
        value={analyticsParams.bucket}
        onValueChange={(v) =>
          setParam({ bucket: v as "month" | "week" | "day" })
        }
      >
        <SelectTrigger className="w-32" aria-label="Grouping">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="month">By month</SelectItem>
          <SelectItem value="week">By week</SelectItem>
          <SelectItem value="day">By day</SelectItem>
        </SelectContent>
      </Select>
    </div>
  );

  if (analyticsLoaded && (!analytics || analytics.cells.length === 0)) {
    return (
      <div>
        {Controls}
        <EmptyState
          seed={13}
          eyebrow="Spending Atlas · No entries"
          title="Nothing to chart yet"
          description="Once transactions are recorded, the atlas plots where money flows, by category and across time."
        />
      </div>
    );
  }

  if (!analytics) {
    return (
      <div>
        {Controls}
        <p className="font-mono text-sm text-muted-foreground">
          Drawing the atlas…
        </p>
      </div>
    );
  }

  const grid = buildHeatGrid(analytics);

  return (
    <div>
      {Controls}
      <div className="overflow-x-auto border border-rule-strong/20 bg-card">
        <table className="w-full border-collapse text-[11px]">
          <thead>
            <tr className="border-b border-rule-strong/30">
              <th className="sticky left-0 z-10 bg-card px-3 py-2 text-left dept-label">
                Category
              </th>
              {grid.buckets.map((b) => (
                <th
                  key={b}
                  className="px-1 py-2 text-center font-mono text-[10px] text-muted-foreground"
                >
                  {bucketLabel(b, analytics.bucket)}
                </th>
              ))}
              <th className="px-2 py-2 text-center dept-label">Trend</th>
              <th className="px-3 py-2 text-right dept-label">Total</th>
            </tr>
          </thead>
          <tbody>
            {grid.categories.map((cat) => {
              const rowVals = grid.buckets.map(
                (b) => grid.matrix[cat]?.[b] ?? 0
              );
              return (
                <tr key={cat} className="border-b border-rule/40">
                  <td className="sticky left-0 z-10 bg-card px-3 py-1.5 font-display text-sm">
                    {cat}
                  </td>
                  {grid.buckets.map((b) => {
                    const v = grid.matrix[cat]?.[b] ?? 0;
                    const alpha =
                      v === 0 ? 0.05 : 0.18 + 0.82 * (v / grid.columnMax[b]);
                    return (
                      <td key={b} className="p-[2px]">
                        <div
                          className="h-7 w-full min-w-[1.5rem]"
                          style={{ background: categoryColor(cat), opacity: alpha }}
                          title={`${cat} · ${bucketLabel(b, analytics.bucket)} · ${formatCurrency(v)}`}
                        />
                      </td>
                    );
                  })}
                  <td className="px-2 align-middle">
                    <Sparkline
                      data={rowVals}
                      width={72}
                      height={18}
                      animate={!reduce}
                    />
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums ink-debit">
                    {formatCurrency(analytics.totals_by_category[cat] ?? 0)}
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="border-t border-rule-strong/40">
              <td className="sticky left-0 z-10 bg-card px-3 py-2 font-sans text-[9px] uppercase tracking-[0.18em] text-muted-foreground">
                Total
              </td>
              {grid.buckets.map((b) => (
                <td
                  key={b}
                  className="px-1 py-2 text-center font-mono text-[9px] text-muted-foreground"
                >
                  {formatCurrency(analytics.totals_by_bucket[b] ?? 0)}
                </td>
              ))}
              <td />
              <td className="px-3 py-2 text-right intaglio text-sm ink-debit">
                {formatCurrency(analytics.grand_total)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
