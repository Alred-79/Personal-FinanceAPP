import { useEffect } from "react";
import { Link } from "react-router-dom";
import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
  ReferenceArea,
} from "recharts";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { ink, hatch, AXIS_TICK, tooltipStyle } from "@/lib/chart";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";
import { Figure } from "@/components/engraving/Figure";
import { Stamp } from "@/components/engraving/Stamp";
import { EmptyState } from "@/components/engraving/EmptyState";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/useToast";

/**
 * The freelancer income-volatility surface (W5): a W-2-vs-self-employment
 * dispersion plot with the recommended Safe-to-Spend buffer drawn as the cushion
 * below the mean — "how much of a good month to hold back so a typical bad month
 * still clears." Recommending and applying are separate (guardrail B2): apply is
 * the one-tap PUT to /settings/preferences/.
 */
export default function IncomeVolatility() {
  const v = useStore((s) => s.incomeVolatility);
  const loaded = useStore((s) => s.incomeVolatilityLoaded);
  const fetchIncomeVolatility = useStore((s) => s.fetchIncomeVolatility);
  const updateS2sPrefs = useStore((s) => s.updateS2sPrefs);
  const { toast } = useToast();

  useEffect(() => {
    fetchIncomeVolatility();
  }, [fetchIncomeVolatility]);

  if (loaded && !v) {
    return (
      <EmptyState
        seed={17}
        eyebrow="Income · Freelancer mode off"
        title="Income smoothing isn't enabled"
        description="When freelancer mode is on, this surface measures how lumpy your self-employment income is and recommends a Safe-to-Spend buffer that rides out a typical low month."
      />
    );
  }
  if (!v) {
    return (
      <p className="font-mono text-sm text-muted-foreground">
        Measuring your income…
      </p>
    );
  }

  const oneIn = v.target_percentile ? Math.round(1 / v.target_percentile) : 5;
  const bandLow = Math.max(0, v.mean_monthly - v.recommended_buffer);
  const applied = Math.abs(v.current_buffer - v.recommended_buffer) < 0.01;

  const apply = async () => {
    await updateS2sPrefs({ s2s_buffer: v.recommended_buffer });
    await fetchIncomeVolatility();
    toast({
      title: "Buffer set",
      description: `Holding back ${formatCurrency(
        v.recommended_buffer
      )} of Safe-to-Spend.`,
    });
  };

  return (
    <div className="space-y-6">
      <Card className="plate-raking">
        <CardContent className="p-4">
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart
              data={v.months}
              margin={{ left: 4, right: 12, top: 8, bottom: 0 }}
            >
              <defs
                dangerouslySetInnerHTML={{
                  __html: hatch("volBand", "--gold", 0.2, 5).def,
                }}
              />
              <CartesianGrid
                stroke={ink("--rule", 0.6)}
                strokeDasharray="2 4"
                vertical={false}
              />
              <XAxis
                dataKey="month"
                tick={{ ...AXIS_TICK, fill: ink("--muted-foreground") }}
                tickFormatter={(m: string) => m.slice(5)}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ ...AXIS_TICK, fill: ink("--muted-foreground") }}
                tickFormatter={(n: number) => `$${Math.round(n / 1000)}k`}
                axisLine={false}
                tickLine={false}
                width={52}
              />
              <Tooltip
                contentStyle={tooltipStyle()}
                formatter={(n: number, key) => [
                  formatCurrency(n),
                  key === "self_employment" ? "Self-employment" : "W-2",
                ]}
              />
              {v.sufficient_data && v.recommended_buffer > 0 && (
                <ReferenceArea
                  y1={bandLow}
                  y2={v.mean_monthly}
                  fill="url(#volBand)"
                  stroke={ink("--gold", 0.35)}
                  strokeDasharray="3 3"
                />
              )}
              {v.sufficient_data && (
                <ReferenceLine
                  y={v.mean_monthly}
                  stroke={ink("--gold", 0.6)}
                  strokeDasharray="4 4"
                />
              )}
              <Bar
                dataKey="self_employment"
                stackId="a"
                fill={ink("--chart-3")}
                maxBarSize={42}
              />
              <Bar
                dataKey="w2"
                stackId="a"
                fill={ink("--chart-1", 0.5)}
                maxBarSize={42}
              />
            </ComposedChart>
          </ResponsiveContainer>
          <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 px-2 font-mono text-[10px] text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <span
                className="h-2 w-3"
                style={{ background: ink("--chart-3") }}
              />
              Self-employment
            </span>
            <span className="flex items-center gap-1.5">
              <span
                className="h-2 w-3"
                style={{ background: ink("--chart-1", 0.5) }}
              />
              W-2
            </span>
            {v.recommended_buffer > 0 && (
              <span className="text-gold">▤ buffer cushion below the mean</span>
            )}
          </p>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardContent className="p-6">
            <p className="dept-label">Recommended Safe-to-Spend buffer</p>
            <div className="mt-1 flex items-baseline gap-3">
              <p className="intaglio text-4xl text-foreground">
                <AnimatedNumber value={v.recommended_buffer} />
              </p>
              {v.sufficient_data && v.recommended_buffer > 0 && (
                <Stamp variant="credit" still>
                  1-in-{oneIn} month covered
                </Stamp>
              )}
            </div>
            <p className="mt-3 border-t border-rule pt-3 font-sans text-[12px] leading-relaxed text-muted-foreground">
              {v.rationale}
            </p>
            {v.recommended_buffer > 0 && (
              <Button className="mt-4" onClick={apply} disabled={applied}>
                {applied
                  ? "Buffer applied"
                  : `Hold back ${formatCurrency(v.recommended_buffer)}`}
              </Button>
            )}
          </CardContent>
        </Card>
        <div className="space-y-3">
          <Figure label="Current buffer" value={formatCurrency(v.current_buffer)} />
          <Figure label="Months observed" value={String(v.months_observed)} />
        </div>
      </div>

      {v.tax_reserve && (
        <Card>
          <CardContent className="p-6">
            <div className="flex items-baseline justify-between gap-2">
              <p className="dept-label">Tax Reserve</p>
              <Link
                to="/goals"
                className="font-sans text-[10px] uppercase tracking-[0.14em] text-gold transition-colors hover:text-foreground"
              >
                View goal →
              </Link>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <Figure
                label="Set aside"
                value={formatCurrency(v.tax_reserve.progress)}
                accent="credit"
              />
              <Figure
                label="Target"
                value={formatCurrency(v.tax_reserve.target)}
              />
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
