/**
 * Outcomes v0 — INTERNAL (v4 §13).
 *
 * A plain page rendering the per-cohort metric comparison with confidence
 * intervals and the honesty footer (sample sizes, caveats). Deliberately
 * unstyled beyond the ledger basics, identical in every mode, with no
 * marketing language anywhere. Publishing anything beyond this internal
 * view is an owner decision (v4 §17).
 */
import { useEffect, useState } from "react";
import PageHeader from "@/components/layout/PageHeader";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useTerm } from "@/store/gameMode";
import api from "@/lib/api";

interface CohortCell {
  n: number;
  mean: number;
  ci_low: number;
  ci_high: number;
}

interface OutcomesData {
  comparison: Record<string, Record<string, CohortCell>>;
  honesty_footer: {
    sample_sizes: Record<string, number>;
    caveats: string[];
  };
}

export default function Outcomes() {
  const [data, setData] = useState<OutcomesData | null>(null);
  const title = useTerm("outcomes.title");

  useEffect(() => {
    api
      .get("/game/outcomes/")
      .then((res) => setData(res.data))
      .catch(() => setData(null));
  }, []);

  const metrics = data ? Object.keys(data.comparison).sort() : [];

  return (
    <div data-testid="outcomes-page">
      <PageHeader
        title={title}
        description="Cohort comparison, money metrics only. Internal."
      />

      {metrics.length === 0 ? (
        <Card>
          <CardContent className="pt-6 text-sm text-muted-foreground">
            No rollups yet.
          </CardContent>
        </Card>
      ) : (
        metrics.map((metric) => {
          const cohorts = data!.comparison[metric];
          return (
            <Card className="mb-4" key={metric}>
              <CardHeader>
                <CardTitle className="text-base font-mono">{metric}</CardTitle>
              </CardHeader>
              <CardContent>
                <table className="w-full text-sm" data-testid={`metric-${metric}`}>
                  <thead>
                    <tr className="text-left text-muted-foreground">
                      <th className="py-1 pr-4">cohort</th>
                      <th className="py-1 pr-4">n</th>
                      <th className="py-1 pr-4">mean</th>
                      <th className="py-1">95% CI</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(cohorts)
                      .sort(([a], [b]) => a.localeCompare(b))
                      .map(([cohort, cell]) => (
                        <tr key={cohort} className="border-t border-border/40">
                          <td className="py-1 pr-4">{cohort}</td>
                          <td className="py-1 pr-4 tabular-nums">{cell.n}</td>
                          <td className="py-1 pr-4 tabular-nums">
                            {cell.mean.toFixed(4)}
                          </td>
                          <td className="py-1 tabular-nums">
                            [{cell.ci_low.toFixed(4)}, {cell.ci_high.toFixed(4)}]
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          );
        })
      )}

      {data ? (
        <Card data-testid="honesty-footer">
          <CardContent className="pt-6">
            <p className="dept-label mb-2 text-[11px]">
              sample sizes:{" "}
              {Object.entries(data.honesty_footer.sample_sizes)
                .map(([cohort, n]) => `${cohort}=${n}`)
                .join(", ") || "none"}
            </p>
            <ul className="list-disc pl-5 text-xs text-muted-foreground">
              {data.honesty_footer.caveats.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
