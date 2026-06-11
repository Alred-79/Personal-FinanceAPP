import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { useNavigate } from "react-router-dom";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

const TICK_STYLE = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
};

export default function ExpensesCard() {
  const { budgets } = useStore();
  const navigate = useNavigate();

  if (budgets.length === 0) {
    return (
      <Card className="shadow-brutal">
        <CardHeader>
          <CardTitle className="font-mono text-xs uppercase tracking-widest text-primary">
            [ BUDGET STATUS ]
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col items-start gap-3 py-6">
          <p className="font-mono text-sm text-muted-foreground">
            No budgets set up yet.
          </p>
          <button
            onClick={() => navigate("/budgets")}
            className="font-mono text-xs uppercase tracking-widest text-primary border border-primary px-3 py-1.5 hover:bg-primary hover:text-primary-foreground transition-colors"
          >
            + Create a budget
          </button>
        </CardContent>
      </Card>
    );
  }

  const data = budgets.map((b) => ({
    name: b.category,
    spent: b.spent,
    limit: b.effective_limit,
    over: b.over_budget,
  }));

  return (
    <Card className="shadow-brutal">
      <CardHeader>
        <CardTitle className="font-mono text-xs uppercase tracking-widest text-primary">
          [ BUDGET STATUS ]
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={Math.max(160, data.length * 36)}>
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }}>
            <XAxis
              type="number"
              tick={{ ...TICK_STYLE, fill: "hsl(150,30%,40%)" }}
              tickFormatter={(v: number) => `$${v}`}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="name"
              tick={{ ...TICK_STYLE, fill: "hsl(145,80%,88%)" }}
              width={90}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              contentStyle={{
                background: "hsl(240,20%,7%)",
                border: "1px solid hsl(150,60%,15%)",
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 12,
                color: "hsl(145,80%,88%)",
              }}
              formatter={(value: number) => [formatCurrency(value)]}
              cursor={{ fill: "rgba(0,255,136,0.05)" }}
            />
            <Bar dataKey="limit" fill="hsl(240,15%,18%)" radius={0} name="Limit" />
            <Bar dataKey="spent" radius={0} name="Spent">
              {data.map((entry, i) => (
                <Cell
                  key={i}
                  fill={entry.over ? "hsl(3,100%,60%)" : "hsl(150,100%,50%)"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>

        {budgets.some((b) => b.over_budget) && (
          <div className="mt-3 flex flex-wrap gap-2">
            {budgets
              .filter((b) => b.over_budget)
              .map((b) => (
                <span
                  key={b.id}
                  className="font-mono text-xs text-destructive border border-destructive px-1.5 py-0.5"
                >
                  ! {b.category.toUpperCase()} OVER BUDGET
                </span>
              ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
