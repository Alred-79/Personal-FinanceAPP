import { useEffect } from "react";
import { useStore } from "@/store/store";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatCurrency } from "@/lib/format";
import { Figure } from "@/components/engraving/Figure";
import { SectionRule } from "@/components/engraving/SectionRule";
import type { ScenarioCompareColumn } from "@/types";

/**
 * Compare view (v6 doc 07): lines up N saved scenarios against one shared
 * baseline column. A comparison ledger table is the primary read; the column
 * metrics reuse the shared {@link Figure} plate.
 */
export default function ScenarioCompare({
  scenarioIds,
  horizonDays = 90,
}: {
  scenarioIds: number[];
  horizonDays?: number;
}) {
  const compareResult = useStore((s) => s.compareResult);
  const compareResultKey = useStore((s) => s.compareResultKey);
  const compareLoading = useStore((s) => s.compareLoading);
  const compareScenarios = useStore((s) => s.compareScenarios);
  const requestKey = `${horizonDays}:${scenarioIds.join(",")}`;

  useEffect(() => {
    if (scenarioIds.length > 0) compareScenarios(scenarioIds, horizonDays);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioIds.join(","), horizonDays]);

  const columns = compareResultKey === requestKey ? compareResult?.columns ?? [] : [];

  if (scenarioIds.length === 0) {
    return (
      <p className="py-8 text-center font-sans text-sm italic text-muted-foreground">
        Pick saved decisions to compare.
      </p>
    );
  }
  if (compareLoading || columns.length === 0) {
    return (
      <p className="py-8 text-center font-sans italic text-muted-foreground">
        Lining up the columns…
      </p>
    );
  }

  return (
    <div className="space-y-5">
      <SectionRule fleuron>Side-by-side</SectionRule>

      {/* The comparison ledger: one row per metric, one column per scenario. */}
      <Card>
        <CardHeader>
          <CardTitle>Comparison</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full border-collapse font-mono text-sm">
            <thead>
              <tr className="ledger-row">
                <th className="px-4 py-2 text-left font-sans text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                  Metric
                </th>
                {columns.map((c, i) => (
                  <th
                    key={i}
                    className="px-4 py-2 text-right font-sans text-[10px] uppercase tracking-[0.18em] text-muted-foreground"
                  >
                    {c.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <MetricRow label="Ending balance" columns={columns} pick={(r) => formatCurrency(r.ending_balance)} />
              <MetricRow label="Lowest point" columns={columns} pick={(r) => formatCurrency(r.lowest_balance)} />
              <MetricRow label="Modeled paths below zero" columns={columns} pick={(r) => `${r.paths_below_zero} of ${r.paths_total}`} />
              <MetricRow label="Runway (days)" columns={columns} pick={(r) => String(r.runway_days)} />
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* Per-column figure plates (the N+1 columns at a glance). */}
      <div className="grid gap-px overflow-hidden border border-rule-strong/30 bg-rule-strong/20 sm:grid-cols-2 lg:grid-cols-3">
        {columns.map((c, i) => (
          <Figure
            key={i}
            label={c.name}
            value={formatCurrency(c.result.ending_balance)}
            accent={c.result.first_negative_date ? "debit" : "credit"}
          />
        ))}
      </div>
    </div>
  );
}

function MetricRow({
  label,
  columns,
  pick,
}: {
  label: string;
  columns: ScenarioCompareColumn[];
  pick: (r: ScenarioCompareColumn["result"]) => string;
}) {
  return (
    <tr className="ledger-row">
      <td className="px-4 py-2 text-left text-muted-foreground">{label}</td>
      {columns.map((c, i) => (
        <td key={i} className="px-4 py-2 text-right tabular-nums text-foreground">
          {pick(c.result)}
        </td>
      ))}
    </tr>
  );
}
