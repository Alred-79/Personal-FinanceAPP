import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { Stamp } from "@/components/engraving/Stamp";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceDot,
  CartesianGrid,
} from "recharts";
import { AXIS_TICK, ink, tooltipStyle } from "@/lib/chart";

/**
 * Cashflow forecast: projects the running balance forward over 30 days from
 * recurring expenses, and flags the lowest point. Surfaces the previously
 * unused `/forecast/` endpoint on the dashboard as a "promissory" plate.
 */
export default function ForecastCard() {
  const { forecast, forecastLoaded, fetchForecast } = useStore();
  const navigate = useNavigate();

  useEffect(() => {
    if (!forecastLoaded) fetchForecast(30);
  }, [forecastLoaded, fetchForecast]);

  const timeline = forecast?.timeline ?? [];

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle>30-Day Cashflow Forecast</CardTitle>
        <button
          onClick={() => navigate("/forecast")}
          className="font-sans text-[10px] uppercase tracking-[0.18em] text-muted-foreground transition-colors hover:text-gold"
        >
          Full forecast →
        </button>
      </CardHeader>
      <CardContent className="space-y-4">
        {timeline.length <= 1 ? (
          <p className="py-8 text-center font-sans text-sm italic text-muted-foreground">
            {forecastLoaded
              ? "No recurring expenses to project. Mark expenses as recurring to see your runway."
              : "Casting the forecast…"}
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="dept-label mb-1">Projected ending balance</p>
                <p className="intaglio text-3xl text-foreground">
                  {formatCurrency(forecast!.ending_balance)}
                </p>
              </div>
              {forecast!.will_go_negative ? (
                <Stamp variant="debit">Goes Negative</Stamp>
              ) : (
                <Stamp variant="credit">Stays Solvent</Stamp>
              )}
            </div>

            <ResponsiveContainer width="100%" height={170}>
              <AreaChart data={timeline} margin={{ left: 0, right: 8, top: 6, bottom: 0 }}>
                <defs>
                  <linearGradient id="forecastFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={ink("--chart-3")} stopOpacity={0.26} />
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
                  minTickGap={28}
                />
                <YAxis
                  tick={{ ...AXIS_TICK, fill: ink("--muted-foreground") }}
                  tickFormatter={(v: number) => `$${Math.round(v)}`}
                  axisLine={false}
                  tickLine={false}
                  width={56}
                />
                <Tooltip
                  contentStyle={tooltipStyle()}
                  formatter={(v: number) => [formatCurrency(v), "Balance"]}
                  cursor={{ stroke: ink("--gold"), strokeWidth: 1, strokeDasharray: "4 4" }}
                />
                <Area
                  type="stepAfter"
                  dataKey="balance"
                  stroke={ink("--chart-3")}
                  strokeWidth={1.8}
                  fill="url(#forecastFill)"
                  dot={false}
                />
                <ReferenceDot
                  x={forecast!.lowest_date}
                  y={forecast!.lowest_balance}
                  r={4}
                  fill={ink("--debit")}
                  stroke={ink("--background")}
                  strokeWidth={1.5}
                />
              </AreaChart>
            </ResponsiveContainer>

            <div className="grid grid-cols-3 gap-3 border-t border-rule pt-3 text-center">
              <Stat label="Lowest point" value={formatCurrency(forecast!.lowest_balance)} accent={forecast!.will_go_negative ? "debit" : undefined} />
              <Stat label="On" value={forecast!.lowest_date.slice(5)} />
              <Stat label="Outflows" value={formatCurrency(forecast!.total_projected_expenses)} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: "debit";
}) {
  return (
    <div>
      <p className="font-sans text-[9px] uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </p>
      <p
        className={`ledger-figures mt-0.5 text-sm ${
          accent === "debit" ? "ink-debit" : "text-foreground"
        }`}
      >
        {value}
      </p>
    </div>
  );
}
