/**
 * THROWAWAY dev harness — renders any REAL page outside auth with a broad seeded
 * store, so the alive treatment can be screenshotted without the backend. Switch
 * page + theme at top. Remove all dev routes before merge.
 */
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { useStore } from "@/store/store";
import { useGameMode, type GameMode } from "@/store/gameMode";
import api from "@/lib/api";

// The Tax page fetches /tax/* directly via axios (not the store), so the store
// seed can't reach it. Patch the shared api instance to answer those GETs with
// mock data in the harness; everything else still hits the (down) backend.
const MOCK_TAX_SUMMARY = {
  tax_year: 2026,
  income_by_source: {
    sources: [
      { issuer: "Acme Corp", form_type: "W-2", income: 82000, withholding: 11400, provenance: "from_document" },
      { issuer: "Freelance — Design", form_type: "1099-NEC", income: 18500, withholding: 0, provenance: "from_ledger" },
      { issuer: "Brokerage", form_type: "1099-DIV", income: 1240, withholding: 0, provenance: "from_document" },
    ],
    total_income: 101740,
    total_withholding: 11400,
  },
  deductions_by_bucket: [
    { bucket: "home_office", label: "Home office", irs_line: "Sch C L30", total: 3600, deductible: 3600 },
    { bucket: "software", label: "Software & subscriptions", irs_line: "Sch C L27a", total: 1450, deductible: 1450 },
    { bucket: "supplies", label: "Supplies", irs_line: "Sch C L22", total: 820, deductible: 820 },
  ],
  mileage: { miles: 1240, rate_cents_per_mile: 67, deduction: 830.8, rate_available: true },
  estimated_quarterly: {
    tax_year: 2026, filing_status: "single", total_income: 101740, wages: 82000, se_income: 18500,
    total_deductible: 6700, se_net_earnings: 17086, se_tax: 2613, income_tax: 14200, state_tax: 0,
    taxable_base: 80000, total_withholding: 11400, payments_made: 0,
    annual_estimate: 16813, remaining_estimate: 5413, per_quarter: 1353,
    safe_harbor_annual: null, safe_harbor_remaining: null, safe_harbor_per_quarter: null,
    due_dates: [["Q1", "Apr 15"], ["Q2", "Jun 16"], ["Q3", "Sep 15"], ["Q4", "Jan 15"]],
    methodology: "Estimated from your tagged income and deductions using 2026 federal brackets; SE tax on 1099 net earnings. A rough planning figure, not a filing.",
    disclaimer: "An estimate for planning only — not tax advice. Confirm with a professional before paying.",
  },
  disclaimer: "Organization only — not tax advice.",
};
const MOCK_TAX_MILEAGE = [
  { id: 1, trip_date: "2026-05-12", miles: 42, purpose: "Client visit", business_personal: "business", tax_year: 2026 },
  { id: 2, trip_date: "2026-04-03", miles: 18.5, purpose: "Supplier pickup", business_personal: "business", tax_year: 2026 },
];
// Rich sample data for the game-layer surfaces (Keeper, Debts, Expedition,
// Campaigns) so they render their POPULATED state in the harness. Real shapes
// matched to each page's fetch (see the page components + service modules).
const gDay = (n: number) => { const d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };
const MOCK_GAME: Record<string, unknown> = {
  "/game/keeper/": {
    stats: {
      vitality: { bucket: "Healthy", months: 4.2 },
      mana: 0.82, armor: 0.64, might: 1.1, low_confidence: false,
    },
    level: 12, xp: 3420, level_progress: 0.62,
  },
  "/game/streak/": { status: "active", current: 23, best: 41, wards: 2, grace_wards: 1, tick_collectible: false },
  "/game/homestead/": { reveal: { projection_date: gDay(28), projection_cents: 184000, accrual_cents: 4200, action: { label: "Set aside $42 now", deep_link: "/goals" } } },
  "/game/bosses/": {
    bosses: [
      { id: 1, name: "The Revolving Balance", kind: "kraken", principal_cents: 340000, minimum_payment_cents: 6000, status: "active", is_active_boss: true, boss: { hp: 204000, starting_hp: 480000, defeated: false, phases_broken: [1] } },
      { id: 2, name: "Auto Loan", kind: "golem", principal_cents: 1280000, minimum_payment_cents: 38000, status: "active", is_active_boss: false, boss: { hp: null, starting_hp: null, defeated: false, phases_broken: [] } },
      { id: 3, name: "Student Loan", kind: "wyrm", principal_cents: 2100000, minimum_payment_cents: 21000, status: "active", is_active_boss: false, boss: { hp: null, starting_hp: null, defeated: false, phases_broken: [] } },
    ],
  },
  "/game/monsters/": {
    monsters: [
      { kind: "minor", key: "Dining", reason: "12 charges this month" },
      { kind: "creeper", key: "Streaming subscriptions", reason: "+$14 vs last month" },
    ],
  },
  "/game/expedition/": {
    map: {
      month: gDay(0).slice(0, 7),
      acts: [
        { index: 1, start: gDay(-6), end: gDay(3), forks: [{ key: "provision", objective: "Provision the month" }] },
        { index: 2, start: gDay(4), end: gDay(13), forks: [{ key: "hold", objective: "Hold the line on dining" }] },
        { index: 3, start: gDay(14), end: gDay(24), forks: [{ key: "bank", objective: "Bank the surplus" }] },
      ],
      nodes: [
        { kind: "bill", day: gDay(-4), label: "Rent" },
        { kind: "income", day: gDay(-2), label: "Payroll" },
        { kind: "rest", day: gDay(2), label: "Quiet week" },
        { kind: "boss", day: gDay(8), label: "Card payment due" },
        { kind: "fog", day: gDay(11), label: "Unscheduled" },
        { kind: "income", day: gDay(13), label: "Payroll" },
        { kind: "bill", day: gDay(18), label: "Utilities" },
      ],
    },
  },
  "/game/campaigns/": {
    campaign: {
      quarter: "2026-Q2", arc_key: "steady-hand", status: "active", rank: "Steward", lifetime_prestige: 7,
      milestones: [
        { key: "m1", label_term: "campaign.milestone.first_surplus", granted: true },
        { key: "m2", label_term: "campaign.milestone.debt_phase", granted: true },
        { key: "m3", label_term: "campaign.milestone.three_streak", granted: false },
        { key: "m4", label_term: "campaign.milestone.full_quarter", granted: false },
      ],
    },
  },
  "/game/challenges/": {
    challenges: [
      { key: "c1", label_term: "challenge.no_spend_week", status: "active" },
      { key: "c2", label_term: "challenge.under_budget_dining", status: "met" },
    ],
    candidates: [],
  },
};

let taxPatched = false;
function patchTaxApi() {
  if (taxPatched) return;
  taxPatched = true;
  const orig = api.get.bind(api);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (api as any).get = (url: string, config?: unknown) => {
    if (url.startsWith("/tax/summary")) return Promise.resolve({ data: MOCK_TAX_SUMMARY });
    if (url.startsWith("/tax/mileage")) return Promise.resolve({ data: MOCK_TAX_MILEAGE });
    if (url.startsWith("/settings/")) return Promise.resolve({ data: { ai: { model: "claude-opus-4-8" }, preferences: { auto_execute_threshold: 100 } } });
    // Game-layer surfaces — strip any query string, then match the path.
    const path = url.split("?")[0];
    if (path in MOCK_GAME) return Promise.resolve({ data: MOCK_GAME[path] });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return orig(url, config as any);
  };
}

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
  Settings: lazy(() => import("@/pages/Settings/Settings")),
  Keeper: lazy(() => import("@/pages/Keeper/Keeper")),
  Debts: lazy(() => import("@/pages/Debts/Debts")),
  Expedition: lazy(() => import("@/pages/Expedition/Expedition")),
  Campaigns: lazy(() => import("@/pages/Campaigns/Campaigns")),
};

function seed() {
  patchTaxApi();
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
    settingsLoaded: true,
    warningPosition: 80,
    savingsPercent: 20,
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

const MODES: GameMode[] = ["off", "ambient", "full"];

export default function DevPreview() {
  const [page, setPage] = useState("Overview");
  const [dark, setDark] = useState(false);
  const [ready, setReady] = useState(false);
  const { mode, setMode } = useGameMode();
  useEffect(() => { document.documentElement.classList.toggle("dark", dark); }, [dark]);
  useEffect(() => {
    seed();
    // DEV-ONLY: expose the store so empty-state showpieces can be driven from
    // the verification harness (e.g. __useStore.setState({ accounts: [] })).
    (window as unknown as { __useStore?: typeof useStore }).__useStore = useStore;
    setReady(true);
  }, []);
  const PageEl = useMemo(() => PAGES[page], [page]);

  return (
    <div style={{ position: "relative", minHeight: "100vh", background: "hsl(var(--background))" }}>
      <div style={{ position: "fixed", top: 8, left: "50%", transform: "translateX(-50%)", zIndex: 9999, display: "flex", gap: ".3rem", background: "hsl(var(--card))", border: "1px solid hsl(var(--rule-strong)/.4)", padding: ".3rem", borderRadius: 8, flexWrap: "wrap", maxWidth: "94vw" }}>
        {Object.keys(PAGES).map((k) => (
          <button key={k} onClick={() => setPage(k)} style={{ fontFamily: "'Spline Sans Mono',monospace", fontSize: ".66rem", padding: ".3rem .55rem", borderRadius: 5, border: "none", cursor: "pointer", background: page === k ? "hsl(var(--gold))" : "transparent", color: page === k ? "hsl(var(--background))" : "hsl(var(--foreground))" }}>{k}</button>
        ))}
        <button onClick={() => setDark((d) => !d)} style={{ fontFamily: "'Spline Sans Mono',monospace", fontSize: ".66rem", padding: ".3rem .55rem", borderRadius: 5, border: "1px solid hsl(var(--rule-strong)/.4)", cursor: "pointer", background: "transparent", color: "hsl(var(--foreground))" }}>◐</button>
        <span style={{ width: 1, alignSelf: "stretch", background: "hsl(var(--rule-strong)/.4)", margin: "0 .15rem" }} />
        {MODES.map((m) => (
          <button key={m} onClick={() => setMode(m)} title="game mode" style={{ fontFamily: "'Spline Sans Mono',monospace", fontSize: ".66rem", padding: ".3rem .55rem", borderRadius: 5, border: "1px solid hsl(var(--rule-strong)/.4)", cursor: "pointer", background: mode === m ? "hsl(var(--game-accent))" : "transparent", color: mode === m ? "hsl(222 45% 11%)" : "hsl(var(--foreground))" }}>⛯ {m}</button>
        ))}
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
