import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";

/** The next evidence behind Safe to Spend, plus the product's primary action. */
export default function ForecastCard() {
  const { forecast, forecastLoaded, fetchForecast } = useStore();
  const navigate = useNavigate();

  useEffect(() => {
    if (!forecastLoaded) void fetchForecast(30);
  }, [forecastLoaded, fetchForecast]);

  const events = [...(forecast?.events ?? [])]
    .filter((event) => event.income > 0 || event.expenses > 0)
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(0, 3);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-4 pb-2">
        <div>
          <CardTitle>Next cash events</CardTitle>
          <p className="mt-1 font-sans text-xs text-muted-foreground">
            The first obligations and income shaping your current answer.
          </p>
        </div>
        <Button onClick={() => navigate("/forecast?tab=whatif")} className="min-h-11 shrink-0">
          Test a decision
        </Button>
      </CardHeader>
      <CardContent>
        {!forecastLoaded ? (
          <div className="h-24 animate-pulse bg-muted/40" aria-label="Loading upcoming cash events" />
        ) : events.length === 0 ? (
          <p className="py-5 text-sm text-muted-foreground">
            Add accounts and record recurring items to estimate upcoming
            obligations, then test how a purchase changes the outcome.
          </p>
        ) : (
          <ol className="divide-y divide-rule" aria-label="Next three projected cash events">
            {events.map((event) => (
              <li key={`${event.date}-${event.label}`} className="flex min-h-11 items-center gap-4 py-2">
                <time className="w-20 shrink-0 font-mono text-xs text-muted-foreground" dateTime={event.date}>
                  {event.date.slice(5)}
                </time>
                <span className="min-w-0 flex-1 truncate font-sans text-sm">{event.label}</span>
                <span className="flex shrink-0 flex-col items-end font-mono text-xs tabular-nums">
                  {event.income > 0 && <span className="text-credit">+{formatCurrency(event.income)} in</span>}
                  {event.expenses > 0 && <span className="text-debit">−{formatCurrency(event.expenses)} out</span>}
                </span>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
