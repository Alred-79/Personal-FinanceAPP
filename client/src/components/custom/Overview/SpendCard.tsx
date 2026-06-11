import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { SpendSettingsDialog } from "@/components/custom/SpendSettingsDialog/SpendSettingsDialog";

function getWeekRange(): { start: string; end: string } {
  const now = new Date();
  const sunday = new Date(now);
  sunday.setDate(now.getDate() - now.getDay());
  const saturday = new Date(sunday);
  saturday.setDate(sunday.getDate() + 6);
  const fmt = (d: Date) =>
    d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return { start: fmt(sunday), end: fmt(saturday) };
}

export default function SpendCard() {
  const { spendOverTime, budgetAllotment, warningPosition, savingsPercent, fixedPerMonth } =
    useStore();

  const safeToSpend = Math.max(0, budgetAllotment - spendOverTime);
  const pct =
    budgetAllotment > 0
      ? Math.min(100, (spendOverTime / budgetAllotment) * 100)
      : 0;
  const isOver = spendOverTime > budgetAllotment;
  const isWarning = !isOver && pct >= warningPosition;
  const { start, end } = getWeekRange();

  const barColor = isOver
    ? "bg-destructive"
    : isWarning
    ? "bg-orange-400"
    : "bg-primary";

  const amountColor = isOver
    ? "text-destructive"
    : isWarning
    ? "text-orange-400"
    : "text-primary";

  return (
    <Card className="shadow-brutal">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="font-mono text-xs uppercase tracking-widest text-primary">
          SPEND
        </CardTitle>
        <SpendSettingsDialog
          onWarningPositionChange={() => {}}
          onSavingsPercentChange={() => {}}
        />
      </CardHeader>

      <CardContent className="space-y-5">
        {/* Safe-to-spend amount */}
        <div className="flex flex-col items-center gap-1 py-2">
          <p className={`font-mono text-4xl font-bold tabular-nums ${amountColor}`}>
            <span className="text-2xl">$</span>
            {safeToSpend.toFixed(0)}
            <span className="text-2xl font-normal">
              .{(safeToSpend % 1).toFixed(2).slice(2)}
            </span>
          </p>
          <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
            Safe-to-Spend
          </p>
          <p className="font-mono text-[10px] text-muted-foreground/60">
            {start} — {end}
          </p>
        </div>

        {/* Progress bar with warning tick */}
        <div className="space-y-2">
          <div className="relative h-2.5 w-full overflow-hidden border-2 border-border bg-secondary">
            {/* Spent bar */}
            <div
              className={`absolute inset-y-0 left-0 transition-all duration-500 ${barColor}`}
              style={{ width: `${pct}%` }}
            />
            {/* Warning threshold tick */}
            {warningPosition > 0 && warningPosition < 100 && (
              <div
                className="absolute inset-y-0 w-px bg-foreground/40"
                style={{ left: `${warningPosition}%` }}
              />
            )}
          </div>

          <div className="flex items-center justify-between font-mono text-[10px] text-muted-foreground">
            <span>$0</span>
            <span
              className={`font-bold ${
                isOver ? "text-destructive" : isWarning ? "text-orange-400" : ""
              }`}
            >
              {pct.toFixed(1)}%{isOver ? " OVER" : ""}
            </span>
            <span>{formatCurrency(budgetAllotment)}</span>
          </div>
        </div>

        {/* Footer stats */}
        <div className="flex justify-between font-mono text-[10px] text-muted-foreground/60">
          {fixedPerMonth > 0 && (
            <span>Fixed: {formatCurrency(fixedPerMonth)}/mo</span>
          )}
          {savingsPercent > 0 && (
            <span className="ml-auto">{savingsPercent}% saved automatically</span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
