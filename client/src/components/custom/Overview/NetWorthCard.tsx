import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
} from "recharts";

const TICK_STYLE = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  fill: "hsl(150,30%,40%)",
};

export default function NetWorthCard() {
  const { netWorth } = useStore();

  const current =
    netWorth.length > 0 ? netWorth[netWorth.length - 1].total : null;

  // Month-over-month delta: compare last snapshot to the most recent snapshot from ~30 days ago
  const delta = (() => {
    if (netWorth.length < 2) return null;
    const last = netWorth[netWorth.length - 1];
    const lastDate = new Date(last.date);
    const targetDate = new Date(lastDate);
    targetDate.setDate(targetDate.getDate() - 30);
    // Find the closest snapshot on or before targetDate
    let prev = netWorth[0];
    for (const snap of netWorth) {
      if (new Date(snap.date) <= targetDate) prev = snap;
    }
    if (prev === last) return null;
    return last.total - prev.total;
  })();

  return (
    <Card className="shadow-brutal">
      <CardHeader>
        <CardTitle className="font-mono text-xs uppercase tracking-widest text-primary">
          [ NET WORTH ]
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {current !== null && (
          <div className="space-y-0.5">
            <p className="font-mono text-3xl font-bold text-primary animate-count-up">
              {formatCurrency(current)}
            </p>
            {delta !== null && (
              <p className={`font-mono text-xs ${delta >= 0 ? "text-primary" : "text-destructive"}`}>
                {delta >= 0 ? "▲" : "▼"} {formatCurrency(Math.abs(delta))} vs 30 days ago
              </p>
            )}
          </div>
        )}

        {netWorth.length === 0 ? (
          <p className="font-mono text-sm text-muted-foreground">
            No data yet — snapshots are taken daily once accounts are linked.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={netWorth} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
              <XAxis
                dataKey="date"
                tick={TICK_STYLE}
                hide
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={TICK_STYLE}
                tickFormatter={(v: number) => `$${v}`}
                axisLine={false}
                tickLine={false}
                width={56}
              />
              <Tooltip
                contentStyle={{
                  background: "hsl(240,20%,7%)",
                  border: "1px solid hsl(150,60%,15%)",
                  fontFamily: "JetBrains Mono, monospace",
                  fontSize: 11,
                  color: "hsl(145,80%,88%)",
                }}
                formatter={(v: number) => [formatCurrency(v), "Net Worth"]}
                cursor={{ stroke: "hsl(150,100%,50%)", strokeWidth: 1, strokeDasharray: "4 4" }}
              />
              <ReferenceLine
                y={0}
                stroke="hsl(150,60%,15%)"
                strokeDasharray="4 4"
              />
              <Line
                type="monotone"
                dataKey="total"
                stroke="hsl(150,100%,50%)"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, fill: "hsl(150,100%,50%)", strokeWidth: 0 }}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
