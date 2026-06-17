/**
 * THROWAWAY dev harness — renders any REAL page outside auth with a broad seeded
 * store, so the alive treatment can be screenshotted without the backend. Switch
 * page + theme at top. Remove all dev routes before merge.
 */
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { useStore } from "@/store/store";

const PAGES: Record<string, React.LazyExoticComponent<React.ComponentType>> = {
  Overview: lazy(() => import("@/pages/Overview/Overview")),
  Accounts: lazy(() => import("@/pages/Accounts/Accounts")),
  Transactions: lazy(() => import("@/pages/Transactions/Transactions")),
  Budgets: lazy(() => import("@/pages/Budgets/Budgets")),
  Goals: lazy(() => import("@/pages/Goals/Goals")),
  Forecast: lazy(() => import("@/pages/Forecast/Forecast")),
  Subscriptions: lazy(() => import("@/pages/Subscriptions/Subscriptions")),
  Reconcile: lazy(() => import("@/pages/Reconcile/Reconcile")),
  Tax: lazy(() => import("@/pages/Tax/Tax")),
};

function seed() {
  const today = new Date();
  const day = (n: number) => { const d = new Date(today); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };
  const txns = [
    { id: 1, title: "Whole Foods", amount: -84.2, date: day(-1), category: "Groceries", type: "expense" },
    { id: 2, title: "Payroll", amount: 2400, date: day(-2), category: "Income", type: "income" },
    { id: 3, title: "Con Edison", amount: -140, date: day(-3), category: "Utilities", type: "expense" },
    { id: 4, title: "Joe's Pizza", amount: -22.5, date: day(-4), category: "Dining", type: "expense" },
    { id: 5, title: "Uber", amount: -18.3, date: day(-5), category: "Transport", type: "expense" },
    { id: 6, title: "Trader Joe's", amount: -56.1, date: day(-6), category: "Groceries", type: "expense" },
  ];
  useStore.setState({
    user: { id: 1, username: "advik", email: "a@b.c" } as never,
    isLoggedIn: true, userLoaded: true, hasLoaded: true, isLoading: false,
    accounts: [
      { id: 1, name: "Everyday Checking", type: "checking", balance: 4210.18, last_updated: day(0), transactions: txns.slice(0, 4) },
      { id: 2, name: "High-Yield Savings", type: "savings", balance: 18400, last_updated: day(0), transactions: [] },
      { id: 3, name: "Travel Card", type: "credit", balance: -612.4, last_updated: day(0), transactions: txns.slice(2, 5) },
    ] as never,
    accountsLoaded: true,
    netWorth: Array.from({ length: 24 }, (_, i) => ({ date: day(-180 + i * 7), total: 22000 + i * 560 + Math.round(Math.sin(i / 3) * 800) })) as never,
    netWorthLoaded: true,
    recentTransactions: txns as never,
    transactions: txns as never,
    budgets: [
      { id: 1, category: "Groceries", monthly_limit: 600, effective_limit: 600, rollover: false, spent: 420, remaining: 180, prorated_target: 500, over_budget: false, on_pace: true },
      { id: 2, category: "Dining", monthly_limit: 300, effective_limit: 300, rollover: false, spent: 290, remaining: 10, prorated_target: 250, over_budget: false, on_pace: false },
      { id: 3, category: "Utilities", monthly_limit: 250, effective_limit: 250, rollover: false, spent: 260, remaining: -10, prorated_target: 220, over_budget: true, on_pace: false },
      { id: 4, category: "Transport", monthly_limit: 200, effective_limit: 200, rollover: false, spent: 90, remaining: 110, prorated_target: 160, over_budget: false, on_pace: true },
    ] as never,
    budgetsLoaded: true,
    goals: [
      { id: 1, name: "Emergency Fund", description: "6 months of expenses", amount: 2000, progress: 1800, deadline: new Date(day(60)), completed: false },
      { id: 2, name: "Vacation", description: "Japan trip", amount: 4000, progress: 1600, deadline: new Date(day(180)), completed: false },
      { id: 3, name: "New Laptop", description: "M-series", amount: 2500, progress: 2375, deadline: new Date(day(30)), completed: false },
    ] as never,
    goalsLoaded: true,
    spendOverTime: 1574, budgetAllotment: 2200,
    safeToSpend: { available: 612.4, daily_plan: 55.6, days_remaining: 11, horizon_end: day(11), breakdown: { upcoming_bills: 480, goal_earmarks: 200, buffer: 150 } } as never,
    subscriptions: [
      { merchant: "NETFLIX.COM", title: "Netflix", amount: 15.49, cadence: "monthly", occurrences: 11, last_date: day(-22), next_date: day(8) },
      { merchant: "SPOTIFY P1ABCD", title: "Spotify", amount: 11.99, cadence: "monthly", occurrences: 8, last_date: day(-27), next_date: day(3) },
      { merchant: "PLANET FITNESS", title: "Planet Fitness", amount: 45, cadence: "monthly", occurrences: 6, last_date: day(-10), next_date: day(20) },
      { merchant: "AMZN PRIME*123", title: "Amazon Prime", amount: 139, cadence: "annually", occurrences: 2, last_date: day(-95), next_date: day(270) },
      { merchant: "NYT*DIGITAL", title: "NYT Digital", amount: 4.25, cadence: "weekly", occurrences: 24, last_date: day(-3), next_date: day(4) },
    ] as never,
    subscriptionsLoaded: true,
    forecast: {
      starting_balance: 4180, ending_balance: 5423, lowest_balance: 240.1, lowest_date: day(22),
      horizon_start: day(0), horizon_end: day(30), will_go_negative: false, total_projected_expenses: 1910,
      timeline: Array.from({ length: 30 }, (_, i) => ({ date: day(i), balance: 4180 + i * 42 + Math.round(Math.sin(i / 4) * 220), change: i % 7 === 0 ? -140 : 5 })),
    } as never,
    forecastLoaded: true, forecastHorizon: 30,
    scenarios: [] as never, scenariosLoaded: true,
  });
}

export default function DevPreview() {
  const [page, setPage] = useState("Overview");
  const [dark, setDark] = useState(false);
  const [ready, setReady] = useState(false);
  useEffect(() => { document.documentElement.classList.toggle("dark", dark); }, [dark]);
  useEffect(() => { seed(); setReady(true); }, []);
  const PageEl = useMemo(() => PAGES[page], [page]);

  return (
    <div style={{ position: "relative", minHeight: "100vh", background: "hsl(var(--background))" }}>
      <div style={{ position: "fixed", top: 8, left: "50%", transform: "translateX(-50%)", zIndex: 9999, display: "flex", gap: ".3rem", background: "hsl(var(--card))", border: "1px solid hsl(var(--rule-strong)/.4)", padding: ".3rem", borderRadius: 8, flexWrap: "wrap", maxWidth: "94vw" }}>
        {Object.keys(PAGES).map((k) => (
          <button key={k} onClick={() => setPage(k)} style={{ fontFamily: "'Spline Sans Mono',monospace", fontSize: ".66rem", padding: ".3rem .55rem", borderRadius: 5, border: "none", cursor: "pointer", background: page === k ? "hsl(var(--gold))" : "transparent", color: page === k ? "hsl(var(--background))" : "hsl(var(--foreground))" }}>{k}</button>
        ))}
        <button onClick={() => setDark((d) => !d)} style={{ fontFamily: "'Spline Sans Mono',monospace", fontSize: ".66rem", padding: ".3rem .55rem", borderRadius: 5, border: "1px solid hsl(var(--rule-strong)/.4)", cursor: "pointer", background: "transparent", color: "hsl(var(--foreground))" }}>◐</button>
      </div>
      <div style={{ maxWidth: 1400, margin: "0 auto", padding: "3.5rem clamp(1rem,4vw,3rem) 4rem" }}>
        {ready && (
          <Suspense fallback={<p style={{ color: "hsl(var(--muted-foreground))" }}>Loading…</p>}>
            <PageEl />
          </Suspense>
        )}
      </div>
    </div>
  );
}
