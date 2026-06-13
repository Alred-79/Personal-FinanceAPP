import { useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { todayLocalISO } from "@/lib/dates";
import {
  ComposedChart,
  Area,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import { AXIS_TICK, ink, tooltipStyle } from "@/lib/chart";

interface CashflowPoint {
  date: string;
  spent?: number; // past actual daily spend
  projIncome?: number; // projected income (forward)
  projExpense?: number; // projected expenses (forward, negative for the bar)
}

/**
 * Unified cashflow timeline: the engraved area of recent actual spending,
 * extended past the "today" rule with the projected recurring cashflows —
 * income up in credit ink, bills down in debit ink. Same card as the old
 * spend timeline; it just learned about the future.
 */
export default function TimelineCard() {
  const { recentTransactions, forecast, forecastLoaded, fetchForecast } = useStore();

  useEffect(() => {
    if (!forecastLoaded) fetchForecast(30);
  }, [forecastLoaded, fetchForecast]);

  const today = todayLocalISO();

  const byDate: Record<string, CashflowPoint> = {};
  recentTransactions.forEach((t) => {
    if (t.type === "expense" && t.date <= today) {
      const p = (byDate[t.date] ??= { date: t.date });
      p.spent = (p.spent ?? 0) + t.amount;
    }
  });
  (forecast?.timeline ?? []).forEach((pt) => {
    if (pt.date <= today) return;
    const income = pt.income ?? 0;
    const expenses = pt.expenses ?? 0;
    if (income === 0 && expenses === 0) return;
    const p = (byDate[pt.date] ??= { date: pt.date });
    if (income > 0) p.projIncome = (p.projIncome ?? 0) + income;
    if (expenses > 0) p.projExpense = (p.projExpense ?? 0) - expenses;
  });

  const data = Object.values(byDate).sort((a, b) =>
    a.date.localeCompare(b.date)
  );
  const hasFuture = data.some((d) => d.date > today);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Cashflow Timeline</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="py-8 text-center font-sans text-sm italic text-muted-foreground">
            No entries posted this period.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={196}>
            <ComposedChart
              data={data}
              margin={{ left: 0, right: 8, top: 6, bottom: 0 }}
              stackOffset="sign"
            >
              <defs>
                <linearGradient id="spendFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={ink("--debit")} stopOpacity={0.28} />
                  <stop offset="100%" stopColor={ink("--debit")} stopOpacity={0} />
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
                hide={data.length > 10}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ ...AXIS_TICK, fill: ink("--muted-foreground") }}
                tickFormatter={(v: number) => `$${v}`}
                axisLine={false}
                tickLine={false}
                width={48}
              />
              <Tooltip
                contentStyle={tooltipStyle()}
                formatter={(v: number, name: string) => {
                  if (name === "projIncome") return [formatCurrency(v), "Expected pay"];
                  if (name === "projExpense")
                    return [formatCurrency(Math.abs(v)), "Expected bill"];
                  return [formatCurrency(v), "Spent"];
                }}
                cursor={{ stroke: ink("--gold"), strokeWidth: 1, strokeDasharray: "4 4" }}
              />
              {/* past actuals */}
              <Area
                type="monotone"
                dataKey="spent"
                stroke={ink("--debit")}
                strokeWidth={1.6}
                fill="url(#spendFill)"
                dot={false}
                activeDot={{ r: 3, fill: ink("--debit"), strokeWidth: 0 }}
              />
              {/* forward projection: income up, bills down */}
              <Bar dataKey="projIncome" fill={ink("--credit", 0.55)} barSize={5} />
              <Bar dataKey="projExpense" fill={ink("--debit", 0.45)} barSize={5} />
              {/* the present moment, ruled */}
              {hasFuture && (
                <ReferenceLine
                  x={today}
                  stroke={ink("--gold")}
                  strokeDasharray="3 3"
                  label={{
                    value: "today",
                    position: "insideTopRight",
                    fontSize: 9,
                    fill: ink("--muted-foreground"),
                  }}
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        )}
        {hasFuture && (
          <p className="mt-1 text-right font-sans text-[10px] text-muted-foreground/70">
            Right of the gold rule: projected recurring pay & bills
          </p>
        )}
      </CardContent>
    </Card>
  );
}
