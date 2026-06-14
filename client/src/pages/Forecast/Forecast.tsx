import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useStore } from "@/store/store";
import PageHeader from "@/components/layout/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { formatCurrency } from "@/lib/format";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";
import { Stamp } from "@/components/engraving/Stamp";
import { SectionRule } from "@/components/engraving/SectionRule";
import { GuillocheBand } from "@/components/engraving/Guilloche";
import { Figure } from "@/components/engraving/Figure";
import CashflowCalendar from "@/components/custom/CashflowCalendar/CashflowCalendar";
import ScenarioBuilder from "@/components/custom/ScenarioBuilder/ScenarioBuilder";
import ScenarioCompare from "@/components/custom/ScenarioCompare/ScenarioCompare";
import CommitConfirmDialog from "@/components/custom/ScenarioBuilder/CommitConfirmDialog";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  ReferenceDot,
  ReferenceArea,
  CartesianGrid,
} from "recharts";
import { AXIS_TICK, ink, tooltipStyle } from "@/lib/chart";
import type { ScenarioMutation } from "@/types";

const HORIZONS = [
  { label: "30 days", value: 30 },
  { label: "60 days", value: 60 },
  { label: "90 days", value: 90 },
  { label: "1 year", value: 365 },
];

/**
 * Forecast page — a "promissory note" projecting the balance forward over a
 * chosen horizon. v6 weaves the scenario surface in: a stacked what-if builder,
 * a baseline-vs-scenario chart overlay, a saved-scenario picker, a compare view,
 * and a real commit affordance (replacing the old dead `?commit=N` banner).
 */
export default function Forecast() {
  const { forecast, forecastLoaded, forecastHorizon, fetchForecast } = useStore();
  const scenarios = useStore((s) => s.scenarios);
  const scenariosLoaded = useStore((s) => s.scenariosLoaded);
  const fetchScenarios = useStore((s) => s.fetchScenarios);
  const activeScenarioResult = useStore((s) => s.activeScenarioResult);
  const [searchParams, setSearchParams] = useSearchParams();

  useEffect(() => {
    fetchForecast(forecastHorizon || 30);
    if (!scenariosLoaded) fetchScenarios();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const timeline = forecast?.timeline ?? [];
  const dips = timeline.filter((p) => p.change < 0);

  // ?goal=<id> / ?commit=<$> pre-seed the builder; ?scenario=<id> deep-links the
  // saved picker. A deep link defaults the active tab to "whatif".
  const goalParam = parseInt(searchParams.get("goal") || "", 10);
  const commitParam = parseInt(searchParams.get("commit") || "", 10);
  const scenarioParam = parseInt(searchParams.get("scenario") || "", 10);
  const deepLinked =
    Number.isFinite(goalParam) ||
    Number.isFinite(commitParam) ||
    Number.isFinite(scenarioParam);

  const [tab, setTab] = useState(deepLinked ? "whatif" : "projection");
  const [pickedScenarioId, setPickedScenarioId] = useState<number | null>(
    Number.isFinite(scenarioParam) ? scenarioParam : null
  );
  const [compareIds, setCompareIds] = useState<number[]>([]);

  // Pre-seed the builder rows from the deep link (a goal contribution or a
  // monthly commitment), folded into the ScenarioBuilder's draft mutations.
  const initialMutations = useMemo<ScenarioMutation[] | undefined>(() => {
    const rows: ScenarioMutation[] = [];
    if (Number.isFinite(goalParam) && goalParam > 0) {
      rows.push({ id: "seed-goal", kind: "goal", goalId: goalParam });
    }
    if (Number.isFinite(commitParam) && commitParam > 0) {
      rows.push({
        id: "seed-commit",
        kind: "income",
        title: "Extra set-aside",
        amount: commitParam,
        recurrence: "monthly",
      });
    }
    return rows.length > 0 ? rows : undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [goalParam, commitParam]);

  const clearParams = () => {
    const next = new URLSearchParams(searchParams);
    ["goal", "commit", "scenario"].forEach((k) => next.delete(k));
    setSearchParams(next, { replace: true });
  };

  // The scenario column's timeline (forecast-backed) for the overlay.
  const scenarioTimeline = activeScenarioResult?.scenario.result.timeline ?? [];
  const troughBand = activeScenarioResult?.scenario.result.trough_band;
  const overdraftProb = activeScenarioResult?.scenario.result.overdraft_probability;

  // Merge baseline + scenario timelines into one dataset keyed by date so the
  // two Area series share an x-axis.
  const overlayData = useMemo(() => {
    const byDate = new Map<string, { date: string; baseline?: number; scenario?: number }>();
    for (const p of timeline) byDate.set(p.date, { date: p.date, baseline: p.balance });
    for (const p of scenarioTimeline) {
      const row = byDate.get(p.date) ?? { date: p.date };
      row.scenario = p.balance;
      byDate.set(p.date, row);
    }
    return Array.from(byDate.values()).sort((a, b) => a.date.localeCompare(b.date));
  }, [timeline, scenarioTimeline]);

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
        <Tabs value={tab} onValueChange={setTab} className="space-y-6">
          <TabsList>
            <TabsTrigger value="projection">Projection</TabsTrigger>
            <TabsTrigger value="whatif">What-If</TabsTrigger>
            <TabsTrigger value="compare">Compare</TabsTrigger>
          </TabsList>

          {/* ── Projection: the live, no-overlay forecast ── */}
          <TabsContent value="projection" className="space-y-6">
            <PromissoryPlate />

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

            <CashflowCalendar forecast={forecast!} />
          </TabsContent>

          {/* ── What-If: the stacked builder + baseline-vs-scenario overlay ── */}
          <TabsContent value="whatif" className="space-y-6">
            <ScenarioBuilder
              initialMutations={initialMutations}
              onSaved={() => fetchScenarios()}
            />

            {activeScenarioResult && (
              <>
                <Card>
                  <CardHeader className="flex flex-row items-center justify-between gap-3">
                    <CardTitle>Baseline vs What-If</CardTitle>
                    {overdraftProb != null && (
                      <Stamp variant={overdraftProb > 0.25 ? "debit" : "credit"} still>
                        Overdraft {Math.round(overdraftProb * 100)}%
                      </Stamp>
                    )}
                  </CardHeader>
                  <CardContent>
                    <ResponsiveContainer width="100%" height={320}>
                      <AreaChart data={overlayData} margin={{ left: 4, right: 12, top: 8, bottom: 0 }}>
                        <defs>
                          <linearGradient id="baseFill" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={ink("--chart-3")} stopOpacity={0.2} />
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
                        <Tooltip contentStyle={tooltipStyle()} />
                        {troughBand && (
                          <ReferenceArea
                            y1={troughBand.low}
                            y2={troughBand.high}
                            fill={ink("--gold", 0.12)}
                            stroke={ink("--gold", 0.3)}
                          />
                        )}
                        <ReferenceLine y={0} stroke={ink("--debit", 0.7)} strokeDasharray="5 5" />
                        <Area
                          type="stepAfter"
                          dataKey="baseline"
                          name="Baseline"
                          stroke={ink("--chart-3")}
                          strokeWidth={2}
                          fill="url(#baseFill)"
                          dot={false}
                          connectNulls
                        />
                        <Area
                          type="stepAfter"
                          dataKey="scenario"
                          name="What-If"
                          stroke={ink("--gold")}
                          strokeWidth={2}
                          strokeDasharray="5 4"
                          fill="none"
                          dot={false}
                          connectNulls
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </CardContent>
                </Card>

                <div className="grid grid-cols-2 gap-px overflow-hidden border border-rule-strong/30 bg-rule-strong/20 sm:grid-cols-4">
                  <Figure
                    label="Baseline ending"
                    value={formatCurrency(activeScenarioResult.baseline.result.ending_balance)}
                  />
                  <Figure
                    label="What-If ending"
                    value={formatCurrency(activeScenarioResult.scenario.result.ending_balance)}
                    accent="credit"
                  />
                  <Figure
                    label="Δ ending"
                    value={formatCurrency(activeScenarioResult.scenario.delta.ending_balance)}
                    accent={activeScenarioResult.scenario.delta.ending_balance < 0 ? "debit" : "credit"}
                  />
                  <Figure
                    label="Δ safe-to-spend"
                    value={formatCurrency(activeScenarioResult.scenario.delta.safe_to_spend)}
                    accent={activeScenarioResult.scenario.delta.safe_to_spend < 0 ? "debit" : "credit"}
                  />
                </div>
              </>
            )}

            {/* Saved-scenario picker + commit affordance. */}
            <Card>
              <CardHeader>
                <CardTitle>Saved scenarios</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {scenarios.length === 0 ? (
                  <p className="font-sans text-sm italic text-muted-foreground">
                    No saved scenarios yet — build one above and Save it.
                  </p>
                ) : (
                  <div className="flex flex-wrap items-center gap-3">
                    <Select
                      value={pickedScenarioId ? String(pickedScenarioId) : ""}
                      onValueChange={(v) => setPickedScenarioId(Number(v))}
                    >
                      <SelectTrigger className="w-60" aria-label="Saved scenario">
                        <SelectValue placeholder="Pick a saved scenario" />
                      </SelectTrigger>
                      <SelectContent>
                        {scenarios.map((s) => (
                          <SelectItem key={s.id} value={String(s.id)}>
                            {s.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {pickedScenarioId != null && (
                      <CommitConfirmDialog
                        scenarioId={pickedScenarioId}
                        name={
                          scenarios.find((s) => s.id === pickedScenarioId)?.name ??
                          "Committed scenario"
                        }
                        onCommitted={clearParams}
                      />
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* ── Compare: N saved scenarios against one baseline ── */}
          <TabsContent value="compare" className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Choose scenarios to compare</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                {scenarios.length === 0 ? (
                  <p className="font-sans text-sm italic text-muted-foreground">
                    Save a couple of scenarios first, then compare them here.
                  </p>
                ) : (
                  scenarios.map((s) => {
                    const on = compareIds.includes(s.id);
                    return (
                      <Button
                        key={s.id}
                        size="sm"
                        variant={on ? "default" : "outline"}
                        onClick={() =>
                          setCompareIds((ids) =>
                            on ? ids.filter((i) => i !== s.id) : [...ids, s.id]
                          )
                        }
                      >
                        {s.name}
                      </Button>
                    );
                  })
                )}
              </CardContent>
            </Card>
            <ScenarioCompare scenarioIds={compareIds} horizonDays={forecastHorizon || 90} />
          </TabsContent>
        </Tabs>
      )}
    </>
  );

  function PromissoryPlate() {
    return (
      <Card className="relative overflow-hidden animate-ink-in">
        <div className="text-gold/40">
          <GuillocheBand height={16} waves={4} seed={9} />
        </div>
        <CardContent className="grid gap-6 p-7 md:grid-cols-[1.3fr_1fr]">
          <div className="space-y-4">
            <p className="dept-label">Projected balance on {forecast!.horizon_end}</p>
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
              value={formatCurrency(forecast!.ending_balance - forecast!.starting_balance)}
            />
          </div>
        </CardContent>
      </Card>
    );
  }
}
