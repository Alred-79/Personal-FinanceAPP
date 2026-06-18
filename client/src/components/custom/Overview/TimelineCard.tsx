import { useEffect } from "react";
import { TiltCard, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useStore } from "@/store/store";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { formatCurrency } from "@/lib/format";
import { todayLocalISO } from "@/lib/dates";
import {
  ComposedChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
  ReferenceDot,
} from "recharts";
import { AXIS_TICK, ink, tooltipStyle } from "@/lib/chart";

interface CashflowPoint {
  date: string;
  spent?: number; // past actual daily spend (money out)
  balance?: number; // projected running balance (forward)
}

/** Compact money label for axis ticks / end marker ("$3.2k", "$420"). */
function compact(v: number): string {
  const sign = v < 0 ? "-" : "";
  const n = Math.abs(Math.round(v));
  if (n >= 1000) {
    const k = n / 1000;
    return `${sign}$${k % 1 === 0 ? k.toFixed(0) : k.toFixed(1)}k`;
  }
  return `${sign}$${n}`;
}

/**
 * Cashflow timeline — two registers joined at the "today" rule. To the left,
 * recent actual daily spending as a debit-ink ridge (its own small-money axis).
 * To the right, the projected running balance as a calm forward line on its own
 * (hidden) axis.
 *
 * The two never share an x-position, so the split axes don't invite a false
 * comparison — they read as one continuous story: "what I've spent lately →
 * today → where the balance is headed". The old single signed axis tried to put
 * a ~$3k paycheque and ~$40 of daily coffee on one scale, which flattened the
 * spend ridge to nothing whenever the forward data was sparse. A balance line
 * keeps its shape down to a single recurring bill. (The deep, full-horizon
 * projection still lives on the Forecast page; this is the dashboard glance.)
 */
export default function TimelineCard() {
  const { recentTransactions, forecast, forecastLoaded, fetchForecast } = useStore();
  const reduced = useReducedMotion();

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

  const fwd = (forecast?.timeline ?? []).filter((pt) => pt.date > today);
  if (forecast && fwd.length > 0) {
    // Anchor the forward line at today so it springs from the gold rule.
    (byDate[today] ??= { date: today }).balance = forecast.starting_balance;
    fwd.forEach((pt) => {
      (byDate[pt.date] ??= { date: pt.date }).balance = pt.balance;
    });
  }

  const data = Object.values(byDate).sort((a, b) => a.date.localeCompare(b.date));
  const hasFuture = fwd.length > 0;
  const lastFwd = hasFuture ? fwd[fwd.length - 1] : null;
  const hasSpend = data.some((d) => d.spent != null);

  return (
    <TiltCard>
      <CardHeader className="flex flex-row items-baseline justify-between gap-3 space-y-0">
        <CardTitle>Cashflow Timeline</CardTitle>
        {lastFwd && (
          <span className="font-sans text-[11px] text-muted-foreground">
            projected{" "}
            <span className="ledger-figures text-foreground">
              {formatCurrency(lastFwd.balance)}
            </span>
          </span>
        )}
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <div className="flex min-h-[196px] flex-col items-center justify-center gap-1 py-8 text-center">
            <p className="font-sans text-sm italic text-muted-foreground">
              No entries posted this period.
            </p>
            <p className="font-sans text-xs text-muted-foreground/70">
              Recent spending and your projected balance will chart here.
            </p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={196}>
            <ComposedChart
              data={data}
              margin={{ left: 0, right: 16, top: 12, bottom: 0 }}
            >
              <defs>
                <linearGradient id="spendFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={ink("--debit")} stopOpacity={0.26} />
                  <stop offset="100%" stopColor={ink("--debit")} stopOpacity={0} />
                </linearGradient>
                <linearGradient id="balFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={ink("--chart-3")} stopOpacity={0.22} />
                  <stop offset="100%" stopColor={ink("--chart-3")} stopOpacity={0} />
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
              {/* left axis — the small-money spend scale (labelled) */}
              <YAxis
                yAxisId="spend"
                tick={{ ...AXIS_TICK, fill: ink("--muted-foreground") }}
                tickFormatter={(v: number) => compact(v)}
                axisLine={false}
                tickLine={false}
                width={44}
              />
              {/* right axis — the balance scale, hidden so two $-axes don't
                  compete; the end marker + tooltip carry the actual figures */}
              <YAxis yAxisId="bal" orientation="right" hide domain={["auto", "auto"]} />
              <Tooltip
                contentStyle={tooltipStyle()}
                formatter={(v: number, name: string) =>
                  name === "balance"
                    ? [formatCurrency(v), "Projected balance"]
                    : [formatCurrency(v), "Spent"]
                }
                cursor={{ stroke: ink("--gold"), strokeWidth: 1, strokeDasharray: "4 4" }}
              />
              {/* past actual spend — debit-ink ridge on the left axis */}
              <Area
                yAxisId="spend"
                type="monotone"
                dataKey="spent"
                stroke={ink("--debit")}
                strokeWidth={1.6}
                fill="url(#spendFill)"
                dot={false}
                activeDot={{ r: 3, fill: ink("--debit"), strokeWidth: 0 }}
                isAnimationActive={!reduced}
                connectNulls={false}
              />
              {/* forward projected balance — calm neutral line on the right axis
                  (balance is a level, not "money in", so not credit-green) */}
              <Area
                yAxisId="bal"
                type="monotone"
                dataKey="balance"
                stroke={ink("--chart-3")}
                strokeWidth={2}
                fill="url(#balFill)"
                dot={false}
                activeDot={{ r: 3, fill: ink("--chart-3"), strokeWidth: 0 }}
                isAnimationActive={!reduced}
                connectNulls={false}
              />
              {/* the present moment, ruled */}
              {hasFuture && (
                <ReferenceLine
                  yAxisId="spend"
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
              {/* projected ending balance, marked at the line's end (the figure
                  itself is shown sober in the header) */}
              {lastFwd && (
                <ReferenceDot
                  yAxisId="bal"
                  x={lastFwd.date}
                  y={lastFwd.balance}
                  r={3.5}
                  fill={ink("--chart-3")}
                  stroke={ink("--background")}
                  strokeWidth={1.5}
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        )}
        {data.length > 0 && (
          <div className="mt-1 flex items-center justify-end gap-3 font-sans text-[10px] text-muted-foreground/70">
            {hasSpend && (
              <span className="inline-flex items-center gap-1">
                <span className="h-1.5 w-3" style={{ background: ink("--debit", 0.6) }} />
                spending to date
              </span>
            )}
            {hasFuture && (
              <span className="inline-flex items-center gap-1">
                <span className="h-1.5 w-3" style={{ background: ink("--chart-3", 0.8) }} />
                projected balance
              </span>
            )}
          </div>
        )}
      </CardContent>
    </TiltCard>
  );
}
