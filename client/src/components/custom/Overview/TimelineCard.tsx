import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useStore } from "@/store/store";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

const TICK_STYLE = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  fill: "hsl(150,30%,40%)",
};

export default function TimelineCard() {
  const { recentTransactions } = useStore();

  const byDate: Record<string, number> = {};
  recentTransactions.forEach((t) => {
    if (t.type === "expense") {
      byDate[t.date] = (byDate[t.date] ?? 0) + t.amount;
    }
  });

  const data = Object.entries(byDate)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, total]) => ({ date, total }));

  if (data.length === 0) {
    return (
      <Card className="shadow-brutal">
        <CardHeader>
          <CardTitle className="font-mono text-xs uppercase tracking-widest text-primary">
            [ SPEND TIMELINE ]
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="font-mono text-sm text-muted-foreground">-- no data --</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="shadow-brutal">
      <CardHeader>
        <CardTitle className="font-mono text-xs uppercase tracking-widest text-primary">
          [ SPEND TIMELINE ]
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={data} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
            <defs>
              <linearGradient id="greenFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="hsl(150,100%,50%)" stopOpacity={0.3} />
                <stop offset="95%" stopColor="hsl(150,100%,50%)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="date"
              tick={TICK_STYLE}
              hide={data.length > 10}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={TICK_STYLE}
              tickFormatter={(v: number) => `$${v}`}
              axisLine={false}
              tickLine={false}
              width={48}
            />
            <Tooltip
              contentStyle={{
                background: "hsl(240,20%,7%)",
                border: "1px solid hsl(150,60%,15%)",
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 11,
                color: "hsl(145,80%,88%)",
              }}
              cursor={{ stroke: "hsl(150,100%,50%)", strokeWidth: 1, strokeDasharray: "4 4" }}
            />
            <Area
              type="monotone"
              dataKey="total"
              stroke="hsl(150,100%,50%)"
              strokeWidth={2}
              fill="url(#greenFill)"
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
