import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useStore } from "@/store/store";
import PageHeader from "@/components/layout/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { formatCurrency } from "@/lib/format";
import { Stamp } from "@/components/engraving/Stamp";
import { SectionRule } from "@/components/engraving/SectionRule";
import { Figure } from "@/components/engraving/Figure";
import CashflowCalendar from "@/components/custom/CashflowCalendar/CashflowCalendar";
import ScenarioBuilder from "@/components/custom/ScenarioBuilder/ScenarioBuilder";
import ScenarioCompare from "@/components/custom/ScenarioCompare/ScenarioCompare";
import PlanComposerPanel from "./PlanComposerPanel";
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

  const baselineTimeline = activeResult?.baseline_timeline ?? [];
  const scenarioTimeline = activeResult?.scenario_timeline ?? [];
  const overlayData = useMemo(() => {
    const byDate = new Map<string, { date: string; baseline?: number; scenario?: number }>();
    for (const point of baselineTimeline) byDate.set(point.date, { date: point.date, baseline: point.balance });
    for (const point of scenarioTimeline) {
      const row = byDate.get(point.date) ?? { date: point.date };
      row.scenario = point.balance;
      byDate.set(point.date, row);
    }
    return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
  }, [baselineTimeline, scenarioTimeline]);

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
            <Card>
              <CardContent className="grid gap-6 p-6 md:grid-cols-[1.2fr_1fr]">
                <div>
                  <p className="font-sans text-sm text-muted-foreground">Central-path balance on {forecast.horizon_end}</p>
                  <p className="intaglio mt-2 text-5xl text-foreground">{formatCurrency(forecast.ending_balance)}</p>
                  <p className="mt-3 max-w-xl text-sm text-muted-foreground">
                    This is a directional estimate from current balances, scheduled cash events, and recent discretionary spending—not an exact future balance.
                  </p>
                  {forecast.paths_total != null && forecast.paths_below_zero != null && (
                    <p className="mt-3 font-mono text-xs text-muted-foreground">
                      {forecast.paths_below_zero} of {forecast.paths_total} modeled paths fell below zero.
                    </p>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-px overflow-hidden border border-rule-strong/30 bg-rule-strong/20">
                  <Figure label="Modeled low point" value={formatCurrency(forecast.lowest_balance)} accent={forecast.will_go_negative ? "debit" : "credit"} />
                  <Figure label="Reached on" value={forecast.lowest_date} />
                  <Figure label="First shortfall" value={forecast.first_negative_date ?? "None in horizon"} />
                  <Figure label="Scheduled outflows" value={formatCurrency(forecast.total_projected_expenses)} />
                </div>
              </CardContent>
            </Card>

            <BalanceChart data={forecast.timeline} />
            {forecast.trough_band && <LowPointRange band={forecast.trough_band} />}
            <EventList events={forecast.events ?? []} />
            <CashflowCalendar forecast={forecast} />
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
                      <Figure label="Modeled paths below zero" value={`${activeResult.scenario.result.paths_below_zero} of ${activeResult.scenario.result.paths_total}`} />
                    </div>
                    <p className="text-sm text-muted-foreground">
                      Under these assumptions, the central path reaches {formatCurrency(activeResult.scenario.result.lowest_balance)}. The modeled low-point range is shown separately below; the chart lines are daily central paths.
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
                {activeResult.scenario.result.trough_band && <LowPointRange band={activeResult.scenario.result.trough_band} />}
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
    <Card>
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
    <Card>
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

function LowPointRange({ band }: { band: { low: number; median: number; high: number } }) {
  const spread = Math.max(band.high - band.low, 1);
  const medianPosition = Math.max(0, Math.min(100, ((band.median - band.low) / spread) * 100));
  return (
    <Card>
      <CardHeader><CardTitle>Modeled low-point range</CardTitle></CardHeader>
      <CardContent>
        <div className="relative h-3 bg-ink-wash" role="img" aria-label={`Modeled low-point bounds run from ${formatCurrency(band.low)} to ${formatCurrency(band.high)}, with a central modeled low of ${formatCurrency(band.median)}`}>
          <span className="absolute inset-y-0 w-1 bg-gold" style={{ left: `${medianPosition}%` }} />
        </div>
        <div className="mt-2 flex justify-between gap-4 font-mono text-xs text-muted-foreground">
          <span>Lower modeled bound {formatCurrency(band.low)}</span>
          <span>Central modeled low {formatCurrency(band.median)}</span>
          <span>Upper modeled bound {formatCurrency(band.high)}</span>
        </div>
        <p className="mt-3 text-sm text-muted-foreground">This range summarizes low points across modeled paths. It is separate from the daily central-path lines above.</p>
      </CardContent>
    </Card>
  );
}

function EventList({ events }: { events: Array<{ date: string; expenses: number; label: string }> }) {
  const obligations = events.filter((event) => event.expenses > 0);
  if (!obligations.length) return <p className="text-sm text-muted-foreground">No scheduled outflows appear in this horizon. Connect or import accounts and mark recurring items to improve the outlook.</p>;
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
