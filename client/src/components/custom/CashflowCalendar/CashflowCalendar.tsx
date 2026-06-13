import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatCurrency } from "@/lib/format";
import { parseLocalISODate, todayLocalISO } from "@/lib/dates";
import type { Forecast } from "@/store/store";

const DAY_LABELS = ["S", "M", "T", "W", "T", "F", "S"];

/**
 * Cashflow calendar (v2): the forecast timeline pivoted into a month grid —
 * each day stamped with its projected net flow (pay in credit ink, bills in
 * debit ink). Pure pivot of data the page already holds; nothing refetched.
 */
export default function CashflowCalendar({ forecast }: { forecast: Forecast }) {
  // Net change per date from the projected timeline (skip the synthetic
  // starting-balance point, which has change 0).
  const changeByDate: Record<string, number> = {};
  forecast.timeline.forEach((pt) => {
    if (pt.change !== 0) changeByDate[pt.date] = pt.change;
  });

  // Build the grid for the month containing horizon_start.
  const start = parseLocalISODate(forecast.horizon_start);
  const year = start.getFullYear();
  const month = start.getMonth();
  const firstDay = new Date(year, month, 1);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const leadingBlanks = firstDay.getDay();
  const todayIso = todayLocalISO();

  const cells: Array<{ iso: string; day: number } | null> = [
    ...Array.from({ length: leadingBlanks }, () => null),
    ...Array.from({ length: daysInMonth }, (_, i) => {
      const day = i + 1;
      const iso = `${year}-${String(month + 1).padStart(2, "0")}-${String(
        day
      ).padStart(2, "0")}`;
      return { iso, day };
    }),
  ];

  const monthLabel = firstDay.toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
  });

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Cashflow Calendar · {monthLabel}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-7 gap-px">
          {DAY_LABELS.map((d, i) => (
            <div
              key={`${d}-${i}`}
              className="pb-1 text-center font-sans text-[9px] uppercase tracking-widest text-muted-foreground"
            >
              {d}
            </div>
          ))}
          {cells.map((cell, i) =>
            cell === null ? (
              <div key={`blank-${i}`} />
            ) : (
              <div
                key={cell.iso}
                className={`flex min-h-[44px] flex-col items-center justify-start border border-rule/40 p-0.5 ${
                  cell.iso === todayIso ? "border-gold/70 bg-secondary/40" : ""
                }`}
              >
                <span className="font-mono text-[10px] text-muted-foreground">
                  {cell.day}
                </span>
                {changeByDate[cell.iso] !== undefined && (
                  <span
                    className={`ledger-figures text-[9px] leading-tight ${
                      changeByDate[cell.iso] > 0 ? "text-credit" : "text-debit"
                    }`}
                    title={formatCurrency(Math.abs(changeByDate[cell.iso]))}
                  >
                    {changeByDate[cell.iso] > 0 ? "+" : "−"}
                    {Math.abs(changeByDate[cell.iso]) >= 1000
                      ? `${(Math.abs(changeByDate[cell.iso]) / 1000).toFixed(1)}k`
                      : Math.abs(changeByDate[cell.iso]).toFixed(0)}
                  </span>
                )}
              </div>
            )
          )}
        </div>
        <p className="mt-2 text-right font-sans text-[10px] text-muted-foreground/70">
          Projected recurring pay (+) and bills (−) by day
        </p>
      </CardContent>
    </Card>
  );
}
