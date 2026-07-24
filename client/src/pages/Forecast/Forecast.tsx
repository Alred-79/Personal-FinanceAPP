import { useEffect, useId, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useStore } from "@/store/store";
import PageHeader from "@/components/layout/PageHeader";
import { Card, TiltCard, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { formatCurrency } from "@/lib/format";
import { Stamp } from "@/components/engraving/Stamp";
import { SectionRule } from "@/components/engraving/SectionRule";
import { Figure } from "@/components/engraving/Figure";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";
import { GuillocheBand } from "@/components/engraving/Guilloche";
import CashflowCalendar from "@/components/custom/CashflowCalendar/CashflowCalendar";
import ScenarioBuilder from "@/components/custom/ScenarioBuilder/ScenarioBuilder";
import ScenarioCompare from "@/components/custom/ScenarioCompare/ScenarioCompare";
import PlanComposerPanel from "./PlanComposerPanel";
import ForecastEvidencePanel from "./ForecastEvidencePanel";
import CommitConfirmDialog from "@/components/custom/ScenarioBuilder/CommitConfirmDialog";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
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

export default function Forecast() {
  const { forecast, forecastLoaded, forecastHorizon, fetchForecast } = useStore();
  const scenarios = useStore((s) => s.scenarios);
  const scenariosLoaded = useStore((s) => s.scenariosLoaded);
  const fetchScenarios = useStore((s) => s.fetchScenarios);
  const storedActiveResult = useStore((s) => s.activeScenarioResult);
  const clearResult = useStore((s) => s.clearActiveScenarioResult);
  const planComposerEnabled = useStore((s) => s.planComposerEnabled);
  const forecastEvidenceEnabled = useStore((s) => s.forecastEvidenceEnabled);
  const [searchParams, setSearchParams] = useSearchParams();
  const [acceptCurrentVisitResult, setAcceptCurrentVisitResult] = useState(false);

  useEffect(() => {
    // A Decision result belongs to the builder instance that evaluated it.
    // Never let a global result from a prior visit reappear beside a fresh form.
    clearResult();
    setAcceptCurrentVisitResult(true);
    void fetchForecast(forecastHorizon || 30);
    if (!scenariosLoaded) void fetchScenarios();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeResult = acceptCurrentVisitResult ? storedActiveResult : null;

  const goalParam = parseInt(searchParams.get("goal") || "", 10);
  const commitParam = parseInt(searchParams.get("commit") || "", 10);
  const scenarioParam = parseInt(searchParams.get("scenario") || "", 10);
  const requestedTab = searchParams.get("tab");
  const deepLinked = Number.isFinite(goalParam) || Number.isFinite(commitParam) || Number.isFinite(scenarioParam);
  const [tab, setTab] = useState(requestedTab === "whatif" || deepLinked ? "whatif" : "projection");
  const [pickedScenarioId, setPickedScenarioId] = useState<number | null>(Number.isFinite(scenarioParam) ? scenarioParam : null);
  const [compareIds, setCompareIds] = useState<number[]>([]);

  const initialMutations = useMemo<ScenarioMutation[] | undefined>(() => {
    const rows: ScenarioMutation[] = [];
    if (Number.isFinite(goalParam) && goalParam > 0) rows.push({ id: "seed-goal", kind: "goal", goalId: goalParam });
    if (Number.isFinite(commitParam) && commitParam > 0) {
      rows.push({ id: "seed-commit", kind: "income", title: "Extra income", amount: commitParam, recurrence: "monthly" });
    }
    return rows.length ? rows : undefined;
  }, [goalParam, commitParam]);

  const changeHorizon = (days: number) => {
    clearResult();
    void fetchForecast(days);
  };
  const clearParams = () => {
    const next = new URLSearchParams(searchParams);
    ["goal", "commit", "scenario", "tab"].forEach((key) => next.delete(key));
    setSearchParams(next, { replace: true });
  };

  const overlayData = useMemo(() => {
    const baselineTimeline = activeResult?.baseline_timeline ?? [];
    const scenarioTimeline = activeResult?.scenario_timeline ?? [];
    const byDate = new Map<string, { date: string; baseline?: number; scenario?: number }>();
    for (const point of baselineTimeline) byDate.set(point.date, { date: point.date, baseline: point.balance });
    for (const point of scenarioTimeline) {
      const row = byDate.get(point.date) ?? { date: point.date };
      row.scenario = point.balance;
      byDate.set(point.date, row);
    }
    return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
  }, [activeResult]);

  return (
    <>
      <PageHeader
        title="Decisions"
        description="Test a purchase or income change against one selected horizon and inspect the assumptions."
        reference="Form 90 · Decision outlook"
        actions={
          <div className="flex flex-wrap gap-1.5" aria-label="Decision horizon">
            {HORIZONS.map((horizon) => (
              <Button key={horizon.value} size="sm" className="min-h-11" variant={forecastHorizon === horizon.value ? "default" : "outline"} aria-pressed={forecastHorizon === horizon.value} onClick={() => changeHorizon(horizon.value)}>
                {horizon.label}
              </Button>
            ))}
          </div>
        }
      />

      {!forecastLoaded || !forecast ? (
        <div className="h-64 animate-pulse bg-muted/40" aria-label="Loading decisions" />
      ) : (
        <Tabs value={tab} onValueChange={setTab} className="space-y-6">
          <TabsList className="grid w-full grid-cols-3 gap-0 sm:flex sm:w-auto sm:gap-1">
            <TabsTrigger className="px-1 tracking-[0.08em] sm:px-3 sm:tracking-[0.18em]" value="projection">Current outlook</TabsTrigger>
            <TabsTrigger className="px-1 tracking-[0.08em] sm:px-3 sm:tracking-[0.18em]" value="whatif">Test a decision</TabsTrigger>
            <TabsTrigger className="px-1 tracking-[0.08em] sm:px-3 sm:tracking-[0.18em]" value="compare">Compare saved</TabsTrigger>
          </TabsList>

          <TabsContent value="projection" className="space-y-6">
            <TiltCard className="relative overflow-hidden animate-ink-in" maxTilt={3}>
              <div className="text-gold/45">
                <GuillocheBand height={15} waves={4} seed={9} />
              </div>
              <CardContent className="grid gap-6 p-6 md:grid-cols-[1.2fr_1fr]">
                <div>
                  <p className="font-sans text-sm text-muted-foreground">Central-path balance on {forecast.horizon_end}</p>
                  <p className="intaglio mt-2 text-5xl text-foreground">
                    <AnimatedNumber value={forecast.ending_balance} duration={650} />
                  </p>
                  <p className="mt-3 max-w-xl text-sm text-muted-foreground">
                    {forecast.model_state === "scheduled_only"
                      ? "This path uses current balances and scheduled cash events. A modeled range is withheld until enough varied spending history exists."
                      : "This is a directional estimate from current balances, scheduled cash events, and recent discretionary spending—not an exact future balance."}
                  </p>
                  {forecast.model_state !== "scheduled_only" && forecast.paths_total != null && forecast.paths_below_zero != null && (
                    <p className="mt-3 font-mono text-xs text-muted-foreground">
                      {forecast.paths_below_zero} of {forecast.paths_total} modeled paths fell below zero.
                    </p>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-px overflow-hidden border border-rule-strong/30 bg-rule-strong/20">
                  <Figure label="Central low point" value={formatCurrency(forecast.lowest_balance)} accent={forecast.will_go_negative ? "debit" : "credit"} />
                  <Figure label="Reached on" value={forecast.lowest_date} />
                  <Figure label="First shortfall" value={forecast.first_negative_date ?? "None in horizon"} />
                  <Figure label="Scheduled outflows" value={formatCurrency(forecast.total_projected_expenses)} />
                </div>
              </CardContent>
            </TiltCard>

            <BalanceChart data={forecast.timeline} />
            {forecast.regime_shift && <RegimeShiftNote shift={forecast.regime_shift} />}
            {forecast.model_state !== "scheduled_only" && forecast.trough_band && (
              <LowPointRange
                band={forecast.trough_band}
                centralPathLow={forecast.lowest_balance}
                startingBalance={forecast.starting_balance}
                horizonDays={forecastHorizon}
                pathsBelowZero={forecast.paths_below_zero}
                pathsTotal={forecast.paths_total}
              />
            )}
            <EventList events={forecast.events ?? []} />
            <CashflowCalendar forecast={forecast} />
            {forecastEvidenceEnabled && (
              <details className="border border-rule bg-card p-5">
                <summary className="cursor-pointer font-sans text-sm font-semibold focus-visible:outline-none">
                  Advanced: forecast evidence
                </summary>
                <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
                  Inspect descriptive observations about prior forecast ranges. This
                  evidence does not automatically tune the model or certify future accuracy.
                </p>
                <div className="mt-5"><ForecastEvidencePanel /></div>
              </details>
            )}
          </TabsContent>

          <TabsContent value="whatif" className="space-y-6">
            <ScenarioBuilder
              initialMutations={initialMutations}
              horizonDays={forecastHorizon}
              horizonStart={forecast.horizon_start}
              horizonEnd={forecast.horizon_end}
              onSaved={() => fetchScenarios()}
            />

            {activeResult && (
              <section className="space-y-6" aria-labelledby="decision-answer">
                <Card raking>
                  <CardHeader className="flex flex-row items-start justify-between gap-3">
                    <div>
                      <CardTitle id="decision-answer">Decision answer</CardTitle>
                      <p className="mt-1 text-sm text-muted-foreground">Evaluated from {activeResult.horizon_start} through {activeResult.horizon_end}.</p>
                    </div>
                    <Stamp variant={activeResult.scenario.result.first_negative_date ? "debit" : "credit"} still>
                      {activeResult.scenario.result.first_negative_date ? "Shortfall modeled" : "No central-path shortfall"}
                    </Stamp>
                  </CardHeader>
                  <CardContent className="space-y-5">
                    <div className="grid grid-cols-2 gap-px overflow-hidden border border-rule-strong/30 bg-rule-strong/20 sm:grid-cols-4">
                      <Figure label="Scenario low point" value={formatCurrency(activeResult.scenario.result.lowest_balance)} />
                      <Figure label="Change vs current" value={formatCurrency(activeResult.scenario.delta.lowest_balance)} accent={activeResult.scenario.delta.lowest_balance < 0 ? "debit" : "credit"} />
                      <Figure label="First shortfall" value={activeResult.scenario.result.first_negative_date ?? "None in horizon"} />
                      {activeResult.scenario.result.model_state !== "scheduled_only" && (
                        <Figure label="Modeled paths below zero" value={`${activeResult.scenario.result.paths_below_zero} of ${activeResult.scenario.result.paths_total}`} />
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground">
                      {activeResult.scenario.result.model_state === "scheduled_only"
                        ? `Under these assumptions, the scheduled central path reaches ${formatCurrency(activeResult.scenario.result.lowest_balance)}. A modeled range is withheld until enough varied history exists.`
                        : `Under these assumptions, the central path reaches ${formatCurrency(activeResult.scenario.result.lowest_balance)}. The modeled low-point range is shown separately below; the chart lines are daily central paths.`}
                    </p>
                    <ChangeStatus
                      applied={activeResult.applied_changes}
                      ignored={activeResult.ignored_changes}
                      canExtend={forecastHorizon < 365}
                      onExtend={() => changeHorizon(365)}
                    />
                  </CardContent>
                </Card>
                <ScenarioChart data={overlayData} />
                {activeResult.scenario.result.model_state !== "scheduled_only" && activeResult.scenario.result.trough_band && (
                  <LowPointRange
                    band={activeResult.scenario.result.trough_band}
                    centralPathLow={activeResult.scenario.result.lowest_balance}
                    horizonDays={forecastHorizon}
                    pathsBelowZero={activeResult.scenario.result.paths_below_zero}
                    pathsTotal={activeResult.scenario.result.paths_total}
                  />
                )}
              </section>
            )}

            <Card raking>
              <CardHeader><CardTitle>Saved decisions</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                {scenarios.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No saved decisions yet. Evaluate one above before saving it.</p>
                ) : (
                  <div className="flex flex-wrap items-center gap-3">
                    <Select value={pickedScenarioId ? String(pickedScenarioId) : ""} onValueChange={(value) => setPickedScenarioId(Number(value))}>
                      <SelectTrigger className="w-64" aria-label="Saved decision"><SelectValue placeholder="Pick a saved decision" /></SelectTrigger>
                      <SelectContent>{scenarios.map((scenario) => <SelectItem key={scenario.id} value={String(scenario.id)}>{scenario.name}</SelectItem>)}</SelectContent>
                    </Select>
                    {pickedScenarioId != null && <CommitConfirmDialog scenarioId={pickedScenarioId} name={scenarios.find((scenario) => scenario.id === pickedScenarioId)?.name ?? "Saved decision"} onCommitted={clearParams} />}
                  </div>
                )}
              </CardContent>
            </Card>

            {planComposerEnabled && (
              <details className="border border-rule bg-card p-5">
                <summary className="cursor-pointer font-sans text-sm font-semibold">Advanced: allocation drafts</summary>
                <div className="mt-5"><PlanComposerPanel /></div>
              </details>
            )}
          </TabsContent>

          <TabsContent value="compare" className="space-y-6">
            <Card raking>
              <CardHeader><CardTitle>Choose saved decisions to compare</CardTitle></CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                {scenarios.length === 0 ? <p className="text-sm text-muted-foreground">Save decisions first, then compare them here.</p> : scenarios.map((scenario) => {
                  const selected = compareIds.includes(scenario.id);
                  return <Button key={scenario.id} size="sm" variant={selected ? "default" : "outline"} aria-pressed={selected} onClick={() => setCompareIds((ids) => selected ? ids.filter((id) => id !== scenario.id) : [...ids, scenario.id])}>{scenario.name}</Button>;
                })}
              </CardContent>
            </Card>
            <ScenarioCompare scenarioIds={compareIds} horizonDays={forecastHorizon} />
          </TabsContent>
        </Tabs>
      )}
    </>
  );
}

function BalanceChart({ data }: { data: Array<{ date: string; balance: number }> }) {
  return (
    <Card raking>
      <div className="text-gold/30"><GuillocheBand height={10} waves={3} seed={12} /></div>
      <CardHeader><CardTitle>Daily central path</CardTitle></CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={data} margin={{ left: 4, right: 12, top: 8 }}>
            <CartesianGrid stroke={ink("--rule", 0.6)} strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey="date" tick={{ ...AXIS_TICK, fill: ink("--muted-foreground") }} tickFormatter={(date: string) => date.slice(5)} axisLine={false} tickLine={false} minTickGap={36} />
            <YAxis tick={{ ...AXIS_TICK, fill: ink("--muted-foreground") }} tickFormatter={(value: number) => `$${Math.round(value)}`} axisLine={false} tickLine={false} width={64} />
            <Tooltip contentStyle={tooltipStyle()} formatter={(value: number) => [formatCurrency(value), "Central path"]} />
            <ReferenceLine y={0} stroke={ink("--debit", 0.7)} strokeDasharray="5 5" />
            <Area type="monotone" dataKey="balance" stroke={ink("--chart-3")} strokeWidth={2} fill={ink("--chart-3", 0.1)} dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

function ScenarioChart({ data }: { data: Array<{ date: string; baseline?: number; scenario?: number }> }) {
  return (
    <Card raking>
      <div className="text-gold/30"><GuillocheBand height={10} waves={3} seed={14} /></div>
      <CardHeader><CardTitle>Daily central paths</CardTitle></CardHeader>
      <CardContent>
        <div className="mb-3 flex flex-wrap gap-4 text-xs text-muted-foreground" aria-hidden>
          <span><span className="mr-1 inline-block h-0.5 w-6 bg-chart-3" />Current</span>
          <span><span className="mr-1 inline-block h-0.5 w-6 border-t-2 border-dashed border-gold" />Decision</span>
        </div>
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={data} margin={{ left: 4, right: 12, top: 8 }}>
            <CartesianGrid stroke={ink("--rule", 0.6)} strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey="date" tick={{ ...AXIS_TICK, fill: ink("--muted-foreground") }} tickFormatter={(date: string) => date.slice(5)} axisLine={false} tickLine={false} minTickGap={36} />
            <YAxis tick={{ ...AXIS_TICK, fill: ink("--muted-foreground") }} tickFormatter={(value: number) => `$${Math.round(value)}`} axisLine={false} tickLine={false} width={64} />
            <Tooltip contentStyle={tooltipStyle()} />
            <ReferenceLine y={0} stroke={ink("--debit", 0.7)} strokeDasharray="5 5" />
            <Area type="monotone" dataKey="baseline" name="Current central path" stroke={ink("--chart-3")} strokeWidth={2} fill={ink("--chart-3", 0.08)} dot={false} connectNulls />
            <Area type="monotone" dataKey="scenario" name="Decision central path" stroke={ink("--gold")} strokeWidth={2} strokeDasharray="5 4" fill="none" dot={false} connectNulls />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

interface LowPointRangeProps {
  band: { low: number; median: number; high: number };
  centralPathLow: number;
  startingBalance?: number;
  horizonDays: number;
  pathsBelowZero?: number;
  pathsTotal?: number;
}

const LOW_POINT_PLOT = { left: 48, right: 592 } as const;

function horizonLabel(days: number): string {
  return days === 365 ? "1 year" : `${days} days`;
}

function LowPointRange({
  band,
  centralPathLow,
  startingBalance,
  horizonDays,
  pathsBelowZero,
  pathsTotal,
}: LowPointRangeProps) {
  const patternId = `low-point-hatch-${useId().replace(/:/g, "")}`;
  const finite = (value: number, fallback = 0) =>
    Number.isFinite(value) ? value : fallback;
  const reportedLow = finite(band.low);
  const reportedHigh = finite(band.high, reportedLow);
  const low = Math.min(reportedLow, reportedHigh);
  const high = Math.max(reportedLow, reportedHigh);
  const median = Math.max(low, Math.min(high, finite(band.median, low)));
  const central = finite(centralPathLow);
  const hasStartingBalance =
    startingBalance != null && Number.isFinite(startingBalance);
  const start = hasStartingBalance ? startingBalance : null;

  // A shared dollar domain makes the width meaningful. Positive-only bands begin
  // at the $0 reference; negative and mixed bands extend left of it. Anchoring the
  // upper end to the starting balance (when the response supplies one) also stops
  // a narrow range from filling the entire card and looking more uncertain than
  // it is. The central path participates in both bounds so its distinct marker is
  // never silently clamped to an edge outside its true value.
  const domainMin = Math.min(0, low, central);
  const domainMax = Math.max(0, high, central, ...(start == null ? [] : [start]));
  const rawDomainSpan = domainMax - domainMin;
  const domainSpan = Math.max(rawDomainSpan, 0.01);
  const plotWidth = LOW_POINT_PLOT.right - LOW_POINT_PLOT.left;
  const xFor = (value: number) => {
    if (rawDomainSpan <= 0) {
      return LOW_POINT_PLOT.left + plotWidth / 2;
    }
    const ratio = Math.max(0, Math.min(1, (value - domainMin) / domainSpan));
    return LOW_POINT_PLOT.left + ratio * plotWidth;
  };
  const percentFor = (value: number) => {
    if (rawDomainSpan <= 0) return 50;
    return Math.max(0, Math.min(100, ((value - domainMin) / domainSpan) * 100));
  };

  const lowX = xFor(low);
  const highX = xFor(high);
  const medianX = xFor(median);
  const centralX = xFor(central);
  const zeroX = xFor(0);
  const startX = start == null ? null : xFor(start);
  const degenerate = Math.abs(high - low) <= 0.005;
  const medianLowOverlap = !degenerate && Math.abs(medianX - lowX) < 14;
  const medianHighOverlap = !degenerate && Math.abs(medianX - highX) < 14;
  const allBandMarkersOverlap = medianLowOverlap && medianHighOverlap;
  const sameMedianLowValue = Math.abs(median - low) <= 0.005;
  const sameMedianHighValue = Math.abs(median - high) <= 0.005;
  const period = horizonLabel(horizonDays);
  const countKnown = pathsBelowZero != null && pathsTotal != null;
  const countText = countKnown
    ? `${pathsBelowZero} of ${pathsTotal} modeled paths fell below $0 over ${period}.`
    : `Modeled across ${period}.`;
  const rangeLabel = degenerate
    ? `The reported bounds and median coincide at ${formatCurrency(low)}.`
    : `Modeled low-point bounds run from ${formatCurrency(low)} to ${formatCurrency(high)}, with a median simulated low of ${formatCurrency(median)}.`;
  const accessibleSummary = `${countText} ${rangeLabel} The central daily path reaches a low of ${formatCurrency(central)}.${start == null ? "" : ` The starting balance is ${formatCurrency(start)}.`}`;

  return (
    <Card raking className="overflow-hidden" data-testid="low-point-range">
      <div className="text-gold/35"><GuillocheBand height={12} waves={4} seed={17} /></div>
      <CardHeader>
        <CardTitle>Modeled low points</CardTitle>
        <p className="mt-1 text-sm text-muted-foreground">
          Across {period}, each simulation contributes its single lowest balance.
          This is a distribution of lows—not a band around each date.
        </p>
        <p className="mt-2 font-mono text-xs text-foreground">{countText}</p>
      </CardHeader>
      <CardContent className="space-y-4">
        <svg
          viewBox="0 0 640 96"
          className="h-24 w-full"
          role="img"
          aria-label={accessibleSummary}
          data-domain-min={domainMin}
          data-domain-max={domainMax}
          data-zero-position={percentFor(0)}
        >
          <defs>
            <pattern id={patternId} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="7" stroke="hsl(var(--gold))" strokeWidth="1" opacity="0.42" />
            </pattern>
          </defs>
          <line x1={LOW_POINT_PLOT.left} x2={LOW_POINT_PLOT.right} y1="46" y2="46" stroke="hsl(var(--rule-strong))" strokeWidth="1" />

          {/* $0 is always in the domain and carries a redundant dashed cue, so
              positive/negative meaning never depends on position or color alone. */}
          <line data-testid="zero-reference" x1={zeroX} x2={zeroX} y1="12" y2="78" stroke="hsl(var(--debit) / 0.7)" strokeWidth="1.5" strokeDasharray="4 4" />
          <text x={zeroX} y="10" textAnchor="middle" fill="hsl(var(--muted-foreground))" fontFamily="ui-monospace, monospace" fontSize="10">$0</text>

          {/* The starting balance anchors the scale without pretending it is one
              of the simulated lows. */}
          {startX != null && (
            <line data-testid="starting-balance-marker" x1={startX} x2={startX} y1="20" y2="34" stroke="hsl(var(--rule-strong))" strokeWidth="1.5" />
          )}

          {degenerate ? (
            <g data-testid="modeled-low-point" data-position={percentFor(low)}>
              <circle cx={lowX} cy="46" r="8" fill="hsl(var(--background))" stroke="hsl(var(--gold))" strokeWidth="2" />
              <circle cx={lowX} cy="46" r="3" fill="hsl(var(--gold))" />
            </g>
          ) : (
            <g
              data-testid="modeled-low-band"
              data-start-position={percentFor(low)}
              data-width={percentFor(high) - percentFor(low)}
            >
              <rect x={lowX} y="34" width={Math.max(highX - lowX, 1)} height="24" fill="hsl(var(--gold) / 0.08)" stroke="hsl(var(--gold) / 0.45)" />
              <rect x={lowX} y="34" width={Math.max(highX - lowX, 1)} height="24" fill={`url(#${patternId})`} />
              <line x1={lowX} x2={lowX} y1="28" y2="64" stroke="hsl(var(--rule-strong))" strokeWidth="2" />
              <line x1={highX} x2={highX} y1="28" y2="64" stroke="hsl(var(--rule-strong))" strokeWidth="2" />
              {!medianLowOverlap && !medianHighOverlap && (
                <g data-testid="median-simulated-marker">
                  <line x1={medianX} x2={medianX} y1="24" y2="68" stroke="hsl(var(--gold))" strokeWidth="2.5" />
                  <circle cx={medianX} cy="24" r="4" fill="hsl(var(--gold))" />
                </g>
              )}
              {allBandMarkersOverlap && (
                <g data-testid="median-range-marker">
                  <circle cx={medianX} cy="28" r="5" fill="hsl(var(--gold))" />
                </g>
              )}
              {medianLowOverlap && !allBandMarkersOverlap && (
                <g data-testid="median-low-marker">
                  <circle cx={lowX} cy="28" r="5" fill="hsl(var(--gold))" />
                </g>
              )}
              {medianHighOverlap && !allBandMarkersOverlap && (
                <g data-testid="median-high-marker">
                  <circle cx={highX} cy="28" r="5" fill="hsl(var(--gold))" />
                </g>
              )}
            </g>
          )}

          {/* A separate diamond identifies the deterministic central daily path;
              it is not mislabeled as the median of the simulations. */}
          <g data-testid="central-path-marker" data-position={percentFor(central)} transform={`translate(${centralX} 78)`}>
            <path d="M 0 -6 L 6 0 L 0 6 L -6 0 Z" fill="hsl(var(--chart-3))" stroke="hsl(var(--background))" strokeWidth="1.5" />
          </g>
        </svg>

        <div className="flex flex-wrap gap-x-5 gap-y-2 font-mono text-xs text-muted-foreground" aria-hidden="true">
          <span><span className="mr-1.5 inline-block h-2.5 w-2.5 rounded-full bg-gold" />Median simulated low</span>
          <span><span className="mr-1.5 inline-block h-2.5 w-2.5 rotate-45 bg-chart-3" />Central daily path low</span>
          <span><span className="mr-1.5 inline-block w-4 border-t border-dashed border-debit" />$0 reference</span>
        </div>

        <div className="grid gap-2 font-mono text-xs text-muted-foreground sm:grid-cols-2 lg:grid-cols-4">
          {degenerate ? (
            <span>Reported bounds and median coincide at {formatCurrency(low)}</span>
          ) : (
            <>
              {allBandMarkersOverlap ? (
                <span>
                  Lower bound / median simulated / upper bound{" "}
                  {sameMedianLowValue && sameMedianHighValue
                    ? formatCurrency(median)
                    : `${formatCurrency(low)} / ${formatCurrency(median)} / ${formatCurrency(high)}`}
                </span>
              ) : medianLowOverlap ? (
                <>
                  <span>
                    Lower bound / median simulated{" "}
                    {sameMedianLowValue
                      ? formatCurrency(low)
                      : `${formatCurrency(low)} / ${formatCurrency(median)}`}
                  </span>
                  <span>Upper modeled bound {formatCurrency(high)}</span>
                </>
              ) : medianHighOverlap ? (
                <>
                  <span>Lower modeled bound {formatCurrency(low)}</span>
                  <span>
                    Median simulated / upper bound{" "}
                    {sameMedianHighValue
                      ? formatCurrency(high)
                      : `${formatCurrency(median)} / ${formatCurrency(high)}`}
                  </span>
                </>
              ) : (
                <>
                  <span>Lower modeled bound {formatCurrency(low)}</span>
                  <span>Median simulated low {formatCurrency(median)}</span>
                  <span>Upper modeled bound {formatCurrency(high)}</span>
                </>
              )}
            </>
          )}
          <span>Central daily path low {formatCurrency(central)}</span>
          {start != null && <span>Starting balance {formatCurrency(start)}</span>}
        </div>
      </CardContent>
    </Card>
  );
}

function RegimeShiftNote({ shift }: { shift: { date: string; delta_per_month: number; direction: "up" | "down" } }) {
  const up = shift.direction === "up";
  const date = new Date(`${shift.date}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return (
    <div className="flex flex-col gap-2 border-y border-rule py-4 sm:flex-row sm:items-baseline sm:justify-between">
      <div>
        <p className="font-sans text-sm font-semibold">Recent spending pace changed</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Around {date}, observed discretionary spending moved {up ? "up" : "down"}. The current outlook weights the newer pace.
        </p>
      </div>
      <Stamp variant={up ? "debit" : "credit"} still>
        {up ? "+" : "−"}{formatCurrency(Math.abs(shift.delta_per_month))}/month
      </Stamp>
    </div>
  );
}

function EventList({ events }: { events: Array<{ date: string; expenses: number; label: string }> }) {
  const obligations = events.filter((event) => event.expenses > 0);
  if (!obligations.length) return <p className="text-sm text-muted-foreground">No scheduled outflows appear in this horizon. Add accounts and record recurring items to improve the outlook.</p>;
  return (
    <div className="space-y-3">
      <SectionRule>Scheduled outflows</SectionRule>
      <Card><CardContent className="divide-y divide-rule p-4">{obligations.map((event) => <div key={`${event.date}-${event.label}`} className="grid min-h-11 grid-cols-[7rem_1fr_auto] items-center gap-3 py-2 text-sm"><time dateTime={event.date} className="font-mono text-muted-foreground">{event.date}</time><span className="truncate">{event.label}</span><span className="font-mono text-debit">−{formatCurrency(event.expenses)}</span></div>)}</CardContent></Card>
    </div>
  );
}

function ChangeStatus({ applied, ignored, canExtend, onExtend }: { applied: Array<{ id: string; detail: string }>; ignored: Array<{ id: string; detail: string; reason_code?: string }>; canExtend: boolean; onExtend: () => void }) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div><h3 className="font-sans text-sm font-semibold">Applied assumptions</h3><ul className="mt-2 space-y-1 text-sm text-muted-foreground">{applied.length ? applied.map((item) => <li key={item.id}>✓ {item.detail}</li>) : <li>None</li>}</ul></div>
      <div><h3 className="font-sans text-sm font-semibold">Ignored assumptions</h3><ul className="mt-2 space-y-2 text-sm text-muted-foreground">{ignored.length ? ignored.map((item) => <li key={item.id}><span className="text-debit">Not applied:</span> {item.detail}{canExtend && ["outside_horizon", "no_occurrence_in_horizon"].includes(item.reason_code ?? "") && <Button size="sm" variant="outline" className="ml-2 min-h-11" onClick={onExtend}>Extend horizon</Button>}</li>) : <li>None</li>}</ul></div>
    </div>
  );
}
