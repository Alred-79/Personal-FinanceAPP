import { cn } from "@/lib/utils";
import { Rise } from "../../shared";

/** Safe-to-Spend — an internally consistent illustrative formula. */
function SafeToSpend() {
  const rows = [
    { l: "Current balance", v: "+$3,500", c: "" },
    { l: "Upcoming bills", v: "−$1,200", c: "ink-debit" },
    { l: "Projected income", v: "+$150", c: "ink-credit" },
    { l: "Goal earmarks + pace", v: "−$1,100", c: "ink-debit" },
    { l: "Buffer", v: "−$500", c: "ink-debit" },
  ];
  return (
    <div className="plate h-full bg-card p-5">
      <p className="dept-label">Illustrative Safe-to-Spend · until next income</p>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="intaglio text-foreground" style={{ fontSize: "clamp(1.8rem,5vw,2.6rem)" }}>
          $121
        </span>
        <span className="text-[0.8rem] text-muted-foreground">/ day · 7 days left</span>
      </div>
      <div className="mt-3 border-t border-rule">
        {rows.map((r) => (
          <div key={r.l} className="flex items-center justify-between border-b border-rule py-1.5">
            <span className="text-[0.8rem] text-muted-foreground">{r.l}</span>
            <span className={cn("figure text-[0.84rem]", r.c)}>{r.v}</span>
          </div>
        ))}
        <div className="flex items-center justify-between py-2">
          <span className="text-[0.82rem] font-semibold">Available</span>
          <span className="figure ink-credit text-[0.96rem]">$850</span>
        </div>
      </div>
    </div>
  );
}

/** Compare — N saved scenarios against one baseline, the real Compare ledger. */
function CompareTable() {
  const cols = ["Baseline", "+ Income", "Cut a bill"];
  const rows: { l: string; v: string[]; c?: (i: number) => string }[] = [
    { l: "Ending", v: ["$1,480", "$2,320", "$1,740"] },
    { l: "Lowest", v: ["−$180", "+$410", "+$60"], c: (i) => (i === 0 ? "ink-debit" : "ink-credit") },
    { l: "Overdraft", v: ["23%", "4%", "12%"], c: (i) => (i === 0 ? "ink-debit" : i === 1 ? "ink-credit" : "text-gold") },
    { l: "Runway", v: ["17d", "30d", "30d"] },
  ];
  return (
    <div className="plate h-full bg-card p-5">
      <p className="dept-label">Compare scenarios</p>
      <table className="mt-3 w-full border-collapse">
        <thead>
          <tr>
            <th className="w-[34%]" />
            {cols.map((c, i) => (
              <th key={c} className={cn("pb-1.5 text-right text-[0.7rem] font-semibold", i === 1 ? "text-gold" : "text-muted-foreground")}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.l} className="border-t border-rule">
              <td className="py-1.5 text-[0.78rem] text-muted-foreground">{r.l}</td>
              {r.v.map((val, i) => (
                <td key={i} className={cn("py-1.5 text-right", "figure text-[0.82rem]", r.c?.(i))}>
                  {val}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Cashflow calendar — projected daily inflows and outflows, day by day. */
function Calendar() {
  // 28 cells; flows keyed by day index
  const flows: Record<number, { v: string; c: string }> = {
    3: { v: "−$1.3k", c: "ink-debit" },
    7: { v: "+$1.9k", c: "ink-credit" },
    11: { v: "−$260", c: "ink-debit" },
    15: { v: "−$180", c: "ink-debit" },
    21: { v: "+$1.9k", c: "ink-credit" },
    25: { v: "−$300", c: "ink-debit" },
  };
  const today = 2;
  return (
    <div className="plate h-full bg-card p-5">
      <p className="dept-label">Cashflow calendar</p>
      <div className="mt-3 grid grid-cols-7 gap-px bg-rule-strong/20">
        {Array.from({ length: 28 }).map((_, d) => {
          const f = flows[d];
          return (
            <div
              key={d}
              className={cn(
                "min-h-[34px] bg-card px-1 py-1",
                d === today && "outline outline-1 outline-gold/60"
              )}
            >
              <div className="text-[0.56rem] text-muted-foreground">{d + 1}</div>
              {f && <div className={cn("figure text-[0.58rem] leading-tight", f.c)}>{f.v}</div>}
            </div>
          );
        })}
      </div>
      <p className="mt-2.5 text-[0.76rem] text-muted-foreground">Projected income (+) and bills (−), by day.</p>
    </div>
  );
}

/** The forecast's supporting surfaces — Safe-to-Spend, Compare, and the calendar. */
export function Vignettes() {
  return (
    <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Rise>
        <SafeToSpend />
      </Rise>
      <Rise delay={0.06}>
        <CompareTable />
      </Rise>
      <Rise delay={0.12}>
        <Calendar />
      </Rise>
    </div>
  );
}
