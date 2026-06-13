import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useStore } from "@/store/store";
import PageHeader from "@/components/layout/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { formatCurrency } from "@/lib/format";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";
import { Stamp } from "@/components/engraving/Stamp";
import { SectionRule } from "@/components/engraving/SectionRule";
import { GuillocheBand } from "@/components/engraving/Guilloche";
import CashflowCalendar from "@/components/custom/CashflowCalendar/CashflowCalendar";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  ReferenceDot,
  CartesianGrid,
} from "recharts";
import { AXIS_TICK, ink, tooltipStyle } from "@/lib/chart";

const HORIZONS = [
  { label: "30 days", value: 30 },
  { label: "60 days", value: 60 },
  { label: "90 days", value: 90 },
  { label: "1 year", value: 365 },
];

/**
 * Forecast page — a "promissory note" projecting the balance forward over a
 * chosen horizon, surfacing the previously-unused `/forecast/` endpoint in
 * full: the running-balance plot, the solvency verdict, and the schedule of
 * dips that draw the balance down.
 */
export default function Forecast() {
  const { forecast, forecastLoaded, forecastHorizon, fetchForecast } = useStore();
  const [searchParams, setSearchParams] = useSearchParams();

  useEffect(() => {
    fetchForecast(forecastHorizon || 30);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const timeline = forecast?.timeline ?? [];
  const dips = timeline.filter((p) => p.change < 0);

  // A "what-if" deep link from the Homestead reveal (e.g. ?commit=25): show the
  // projected lift from setting aside $N more each month over this horizon.
  const commitParam = parseInt(searchParams.get("commit") || "", 10);
  const commit = Number.isFinite(commitParam) && commitParam > 0 ? commitParam : null;
  const months =
    forecast && forecast.timeline.length > 1
      ? Math.max(1, Math.round((forecastHorizon || 30) / 30))
      : 0;
  const dismissCommit = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("commit");
    setSearchParams(next, { replace: true });
  };

  return (
    <>
      <PageHeader
        title="Forecast"
        description="Where your balance is headed, projected from recurring obligations."
        reference="Form 90 · Cashflow Projection"
        actions={
          <div className="flex flex-wrap gap-1.5">
            {HORIZONS.map((h) => (
              <Button
                key={h.value}
                size="sm"
                variant={forecastHorizon === h.value ? "default" : "outline"}
                onClick={() => fetchForecast(h.value)}
              >
                {h.label}
              </Button>
            ))}
          </div>
        }
      />

      {!forecastLoaded ? (
        <p className="py-16 text-center font-sans italic text-muted-foreground">
          Casting the projection…
        </p>
      ) : timeline.length <= 1 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <p className="font-display text-2xl">Nothing to project yet</p>
            <p className="max-w-md font-sans text-sm text-muted-foreground">
              The forecast walks your <em>recurring</em> expenses forward from
              today's balance. Mark a few expenses as recurring and they'll
              appear here as a runway.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6">
          {/* What-if banner from a Homestead deep link (?commit=N). */}
          {commit && months > 0 && (
            <Card className="relative overflow-hidden border-gold/50 animate-rise-in">
              <CardContent className="flex flex-wrap items-center justify-between gap-3 p-5">
                <div>
                  <p className="dept-label text-gold">What if you committed more?</p>
                  <p className="mt-1 font-sans text-sm text-muted-foreground">
                    Setting aside{" "}
                    <span className="font-mono font-semibold text-foreground">
                      {formatCurrency(commit)}/mo
                    </span>{" "}
                    would add about{" "}
                    <span className="ledger-figures font-semibold text-credit">
                      {formatCurrency(commit * months)}
                    </span>{" "}
                    over this {months === 12 ? "year" : `${months}-month`} window —
                    lifting your projected balance to{" "}
                    <span className="ledger-figures font-semibold text-foreground">
                      {formatCurrency(forecast!.ending_balance + commit * months)}
                    </span>
                    .
                  </p>
                </div>
                <Button size="sm" variant="outline" onClick={dismissCommit}>
                  Dismiss
                </Button>
              </CardContent>
            </Card>
          )}

          {/* The promissory plate */}
          <Card className="relative overflow-hidden animate-ink-in">
            <div className="text-gold/40">
              <GuillocheBand height={16} waves={4} seed={9} />
            </div>
            <CardContent className="grid gap-6 p-7 md:grid-cols-[1.3fr_1fr]">
              <div className="space-y-4">
                <p className="dept-label">
                  Projected balance on {forecast!.horizon_end}
                </p>
                <p className="intaglio text-5xl text-foreground md:text-6xl">
                  <AnimatedNumber value={forecast!.ending_balance} />
                </p>
                <div className="flex items-center gap-3">
                  {forecast!.will_go_negative ? (
                    <Stamp variant="debit">Projected Overdraft</Stamp>
                  ) : (
                    <Stamp variant="credit">Remains Solvent</Stamp>
                  )}
                  <span className="font-sans text-sm text-muted-foreground">
                    starting from {formatCurrency(forecast!.starting_balance)}
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-px self-center overflow-hidden border border-rule-strong/30 bg-rule-strong/20">
                <Figure
                  label="Lowest point"
                  value={formatCurrency(forecast!.lowest_balance)}
                  accent={forecast!.will_go_negative ? "debit" : "credit"}
                />
                <Figure label="Reached on" value={forecast!.lowest_date} />
                <Figure
                  label="Total outflows"
                  value={formatCurrency(forecast!.total_projected_expenses)}
                  accent="debit"
                />
                <Figure
                  label="Net change"
                  value={formatCurrency(
                    forecast!.ending_balance - forecast!.starting_balance
                  )}
                />
              </div>
            </CardContent>
          </Card>

          {/* The running-balance plot */}
          <Card>
            <CardHeader>
              <CardTitle>Running Balance</CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={320}>
                <AreaChart data={timeline} margin={{ left: 4, right: 12, top: 8, bottom: 0 }}>
                  <defs>
                    <linearGradient id="runFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={ink("--chart-3")} stopOpacity={0.24} />
                      <stop offset="100%" stopColor={ink("--chart-3")} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke={ink("--rule", 0.6)} strokeDasharray="2 4" vertical={false} />
                  <XAxis
                    dataKey="date"
                    tick={{ ...AXIS_TICK, fill: ink("--muted-foreground") }}
                    tickFormatter={(d: string) => d.slice(5)}
                    axisLine={false}
                    tickLine={false}
                    minTickGap={36}
                  />
                  <YAxis
                    tick={{ ...AXIS_TICK, fill: ink("--muted-foreground") }}
                    tickFormatter={(v: number) => `$${Math.round(v)}`}
                    axisLine={false}
                    tickLine={false}
                    width={64}
                  />
                  <Tooltip
                    contentStyle={tooltipStyle()}
                    formatter={(v: number) => [formatCurrency(v), "Balance"]}
                    cursor={{ stroke: ink("--gold"), strokeWidth: 1, strokeDasharray: "4 4" }}
                  />
                  <ReferenceLine y={0} stroke={ink("--debit", 0.7)} strokeDasharray="5 5" />
                  <Area
                    type="stepAfter"
                    dataKey="balance"
                    stroke={ink("--chart-3")}
                    strokeWidth={2}
                    fill="url(#runFill)"
                    dot={false}
                  />
                  <ReferenceDot
                    x={forecast!.lowest_date}
                    y={forecast!.lowest_balance}
                    r={5}
                    fill={forecast!.will_go_negative ? ink("--debit") : ink("--gold")}
                    stroke={ink("--background")}
                    strokeWidth={2}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          {/* The schedule of obligations */}
          {dips.length > 0 && (
            <div className="space-y-3">
              <SectionRule>Schedule of Projected Obligations</SectionRule>
              <Card>
                <CardContent className="p-0">
                  <div className="grid grid-cols-[1fr_auto_auto] gap-x-6 px-6 py-3 font-sans text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                    <span>Date</span>
                    <span className="text-right">Outflow</span>
                    <span className="text-right">Balance after</span>
                  </div>
                  <div className="px-6">
                    {dips.map((p, i) => (
                      <div
                        key={i}
                        className="ledger-row grid grid-cols-[1fr_auto_auto] items-center gap-x-6 py-2.5 font-mono text-sm"
                      >
                        <span className="text-foreground">{p.date}</span>
                        <span className="ink-debit text-right tabular-nums">
                          {formatCurrency(p.change)}
                        </span>
                        <span
                          className={`text-right tabular-nums ${
                            p.balance < 0 ? "ink-debit" : "text-muted-foreground"
                          }`}
                        >
                          {formatCurrency(p.balance)}
                        </span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* The month, pivoted by day (v2 calendar view) */}
          <CashflowCalendar forecast={forecast!} />
        </div>
      )}
    </>
  );
}

function Figure({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: "debit" | "credit";
}) {
  return (
    <div className="bg-card p-4">
      <p className="font-sans text-[9px] uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </p>
      <p
        className={`ledger-figures mt-1 text-base ${
          accent === "debit"
            ? "ink-debit"
            : accent === "credit"
            ? "ink-credit"
            : "text-foreground"
        }`}
      >
        {value}
      </p>
    </div>
  );
}
