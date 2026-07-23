import { useEffect, useState } from "react";

import api from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Stamp } from "@/components/engraving/Stamp";

type Stats = {
  sample_count: number;
  observed_coverage: number | null;
  coverage_95pct_interval: [number, number] | null;
  mean_interval_width: number | null;
  mean_winkler_score: number | null;
  overdraft_event_count: number;
  overdraft_event_prevalence: number | null;
};

type Evidence = {
  descriptive_only: true;
  label: string;
  capture: {
    first_date: string | null;
    last_date: string | null;
    observed_days: number;
    scheduled_days: number;
    completeness: number | null;
    eligible_days: number;
  };
  horizons: Array<{
    horizon_days: number;
    counts: Record<string, number>;
    invalid_reasons: Record<string, number>;
    all_origins: Stats;
    predeclared_disjoint_origins: Stats;
  }>;
  caveats: string[];
};

const pct = (value: number | null) =>
  value == null ? "—" : `${Math.round(value * 100)}%`;

/** Owner-only audit surface. It reports observations and never changes a band. */
export default function ForecastEvidencePanel() {
  const [data, setData] = useState<Evidence | null>(null);

  useEffect(() => {
    let live = true;
    api.get<Evidence>("/forecast/evidence/")
      .then((response) => live && setData(response.data))
      .catch(() => live && setData(null));
    return () => { live = false; };
  }, []);

  if (!data) return null;
  return (
    <Card raking>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div>
          <CardTitle>Forecast evidence pilot</CardTitle>
          <p className="mt-1 font-sans text-xs text-muted-foreground">
            Descriptive observations only—not calibration and not a deployment gate.
          </p>
        </div>
        <Stamp still>{data.capture.observed_days} UTC days</Stamp>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-px overflow-hidden border border-rule-strong/30 bg-rule-strong/20 sm:grid-cols-3">
          <div className="bg-card p-4">
            <p className="dept-label">Capture completeness</p>
            <p className="figure mt-1">{pct(data.capture.completeness)}</p>
          </div>
          <div className="bg-card p-4">
            <p className="dept-label">Eligible days</p>
            <p className="figure mt-1">{data.capture.eligible_days}</p>
          </div>
          <div className="bg-card p-4">
            <p className="dept-label">Operating date</p>
            <p className="figure mt-1">UTC</p>
          </div>
        </div>

        <div className="overflow-x-auto border border-rule-strong/30">
          <table className="w-full text-left font-sans text-xs">
            <thead className="border-b border-rule-strong/30 text-muted-foreground">
              <tr>
                <th className="p-3">Horizon</th>
                <th className="p-3">Valid</th>
                <th className="p-3">Observed coverage</th>
                <th className="p-3">Mean width</th>
                <th className="p-3">Disjoint sample</th>
              </tr>
            </thead>
            <tbody>
              {data.horizons.map((row) => (
                <tr key={row.horizon_days} className="border-b border-rule/50 last:border-0">
                  <td className="p-3 font-mono">{row.horizon_days} days</td>
                  <td className="p-3 font-mono">{row.counts.valid ?? 0}</td>
                  <td className="p-3 font-mono">{pct(row.all_origins.observed_coverage)}</td>
                  <td className="p-3 font-mono">
                    {row.all_origins.mean_interval_width == null
                      ? "—"
                      : formatCurrency(row.all_origins.mean_interval_width)}
                  </td>
                  <td className="p-3 font-mono">
                    {row.predeclared_disjoint_origins.sample_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="font-sans text-[11px] leading-relaxed text-muted-foreground">
          Overlapping forecasts are dependent. The separately predeclared disjoint
          stream is the conservative comparison; their effective sample size is lower
          than the row count, and no automatic “enough data” threshold is applied.
        </p>
      </CardContent>
    </Card>
  );
}
