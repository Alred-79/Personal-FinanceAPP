import { TiltCard, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  CartesianGrid,
} from "recharts";
import { AXIS_TICK, ink, tooltipStyle } from "@/lib/chart";

/** Net-worth trend as a fine engraved line on ruled chart paper. */
export default function NetWorthCard() {
  const { netWorth } = useStore();

  const current = netWorth.length > 0 ? netWorth[netWorth.length - 1].total : null;

  const delta = (() => {
    if (netWorth.length < 2) return null;
    const last = netWorth[netWorth.length - 1];
    const targetDate = new Date(last.date);
    targetDate.setDate(targetDate.getDate() - 30);
    let prev = netWorth[0];
    for (const snap of netWorth) {
      if (new Date(snap.date) <= targetDate) prev = snap;
    }
    if (prev === last) return null;
    return last.total - prev.total;
  })();

  return (
    <TiltCard>
      <CardHeader>
        <CardTitle>Net Worth Trend</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {current !== null && (
          <div className="flex items-baseline gap-3">
            <p className="intaglio text-2xl text-foreground animate-count-up">
              {formatCurrency(current)}
            </p>
            {delta !== null && (
              <p
                className={`font-mono text-xs ${
                  delta >= 0 ? "ink-credit" : "ink-debit"
                }`}
              >
                {delta >= 0 ? "▲" : "▼"} {formatCurrency(Math.abs(delta))}
              </p>
            )}
          </div>
        )}

        {netWorth.length === 0 ? (
          <p className="py-6 font-sans text-sm italic text-muted-foreground">
            No snapshots recorded yet — these are taken daily once accounts are linked.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={176}>
            <LineChart data={netWorth} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
              <CartesianGrid
                stroke={ink("--rule", 0.6)}
                strokeDasharray="2 4"
                vertical={false}
              />
              <XAxis dataKey="date" hide axisLine={false} tickLine={false} />
              <YAxis
                tick={{ ...AXIS_TICK, fill: ink("--muted-foreground") }}
                tickFormatter={(v: number) => `$${v}`}
                axisLine={false}
                tickLine={false}
                width={56}
              />
              <Tooltip
                contentStyle={tooltipStyle()}
                formatter={(v: number) => [formatCurrency(v), "Net Worth"]}
                cursor={{ stroke: ink("--gold"), strokeWidth: 1, strokeDasharray: "4 4" }}
              />
              <ReferenceLine y={0} stroke={ink("--rule-strong", 0.5)} strokeDasharray="4 4" />
              <Line
                type="monotone"
                dataKey="total"
                stroke={ink("--credit")}
                strokeWidth={1.8}
                dot={false}
                activeDot={{ r: 3.5, fill: ink("--credit"), strokeWidth: 0 }}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </TiltCard>
  );
}
