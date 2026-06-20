import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceDot,
  ReferenceLine,
} from "recharts";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { ink, AXIS_TICK, tooltipStyle } from "@/lib/chart";
import { Figure } from "@/components/engraving/Figure";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";
import { TiltCard, Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/engraving/EmptyState";
import { netWorthStats } from "@/lib/almanac";
import { useReducedMotion } from "@/hooks/useEnvironment";

const signed = (n: number) =>
  `${n >= 0 ? "+" : "−"}${formatCurrency(Math.abs(n))}`;
const accentOf = (n: number): "credit" | "debit" | undefined =>
  n > 0 ? "credit" : n < 0 ? "debit" : undefined;

/** The net-worth trend tab: a headline plate, an engraved area chart, a
 *  one-line narrative, and 30/90/365-day deltas. */
export default function NetWorthTrend() {
  const netWorth = useStore((s) => s.netWorth);
  const reduce = useReducedMotion();
  const stats = netWorthStats(netWorth);

  if (!stats) {
    return (
      <EmptyState
        seed={15}
        eyebrow="Net Worth · No history yet"
        title="The trend writes itself"
        description="A snapshot of your net worth is recorded each day. Once a few have stacked up, the line and its story appear here."
      />
    );
  }

  const dir =
    stats.perMonth > 1
      ? "growing"
      : stats.perMonth < -1
      ? "slipping"
      : "holding flat";
  const atHigh = Math.abs(stats.current - stats.athValue) < 1;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <TiltCard className="lg:col-span-1">
          <CardContent className="p-6">
            <p className="dept-label">Net worth</p>
            <p className="intaglio mt-1 text-4xl">
              <AnimatedNumber value={stats.current} />
            </p>
            <p className="mt-3 border-t border-rule pt-3 font-sans text-[12px] leading-relaxed text-muted-foreground">
              {dir === "holding flat" ? (
                <>Holding roughly flat over the recorded span.</>
              ) : (
                <>
                  <span
                    className={
                      stats.perMonth > 0 ? "text-credit" : "text-debit"
                    }
                  >
                    {dir}
                  </span>{" "}
                  about {signed(stats.perMonth)}/mo.
                </>
              )}{" "}
              {atHigh
                ? "At an all-time high."
                : `All-time high ${formatCurrency(stats.athValue)}.`}
            </p>
          </CardContent>
        </TiltCard>

        <Card className="plate-raking lg:col-span-2">
          <CardContent className="p-4">
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart
                data={netWorth}
                margin={{ left: 4, right: 12, top: 8, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="nwFill" x1="0" y1="0" x2="0" y2="1">
                    <stop
                      offset="0%"
                      stopColor={ink("--chart-3")}
                      stopOpacity={0.24}
                    />
                    <stop
                      offset="100%"
                      stopColor={ink("--chart-3")}
                      stopOpacity={0}
                    />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  stroke={ink("--rule", 0.6)}
                  strokeDasharray="2 4"
                  vertical={false}
                />
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
                  tickFormatter={(v: number) => `$${Math.round(v / 1000)}k`}
                  axisLine={false}
                  tickLine={false}
                  width={52}
                />
                <Tooltip
                  contentStyle={tooltipStyle()}
                  formatter={(v: number) => [formatCurrency(v), "Net worth"]}
                  cursor={{
                    stroke: ink("--gold"),
                    strokeWidth: 1,
                    strokeDasharray: "4 4",
                  }}
                />
                <ReferenceLine
                  y={netWorth[0].total}
                  stroke={ink("--rule-strong", 0.5)}
                  strokeDasharray="5 5"
                />
                <Area
                  type="monotone"
                  dataKey="total"
                  stroke={ink("--chart-3")}
                  strokeWidth={2}
                  fill="url(#nwFill)"
                  dot={false}
                  isAnimationActive={!reduce}
                />
                <ReferenceDot
                  x={stats.athDate}
                  y={stats.athValue}
                  r={4}
                  fill={ink("--gold")}
                  stroke={ink("--background")}
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Figure label="30 days" value={signed(stats.delta30)} accent={accentOf(stats.delta30)} />
        <Figure label="90 days" value={signed(stats.delta90)} accent={accentOf(stats.delta90)} />
        <Figure label="365 days" value={signed(stats.delta365)} accent={accentOf(stats.delta365)} />
      </div>
    </div>
  );
}
