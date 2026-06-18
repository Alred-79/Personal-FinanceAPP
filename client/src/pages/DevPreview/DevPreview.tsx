// DEV-ONLY, remove after review — throwaway visual harness for Tier 4 surfaces.
// Seeds the store with rich / sparse / empty fixtures and renders a single
// surface in isolation (no auth, no backend). Reached at /dev-preview (a public
// route in main.tsx, also flagged DEV-ONLY). Delete both before any merge.
import { useEffect, useRef, useState } from "react";
import { useStore } from "@/store/store";
import api from "@/lib/api";
import { toLocalISODate } from "@/lib/dates";
import type { Transaction, Notification, ForecastPoint } from "@/types";
import type { Forecast } from "@/store/store";
import TimelineCard from "@/components/custom/Overview/TimelineCard";
import NotificationBell from "@/components/custom/NotificationBell/NotificationBell";
import { CommandDeck } from "@/components/custom/CommandDeck/CommandDeck";
import { ChroniclerDrawer } from "@/components/custom/ChroniclerDrawer/ChroniclerDrawer";

type Dataset = "rich" | "sparse" | "empty";
type Surface = "timeline" | "notifications" | "deck" | "chronicler";

function dayOffset(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return toLocalISODate(d);
}

function buildTransactions(set: Dataset): Transaction[] {
  if (set === "empty") return [];
  const cats = ["Food", "Transport", "Shopping", "Coffee"];
  if (set === "sparse") {
    return [
      { id: 1, title: "Coffee", date: dayOffset(-2), amount: 6, category: "Coffee", type: "expense" },
      { id: 2, title: "Lunch", date: dayOffset(-1), amount: 18, category: "Food", type: "expense" },
    ];
  }
  // rich: ~14 days of daily spend
  const txns: Transaction[] = [];
  for (let i = 14; i >= 1; i--) {
    const amt = 12 + ((i * 37) % 90); // pseudo-varied
    txns.push({
      id: 100 + i,
      title: cats[i % cats.length],
      date: dayOffset(-i),
      amount: amt,
      category: cats[i % cats.length],
      type: "expense",
    });
  }
  return txns;
}

function buildForecast(set: Dataset): Forecast | null {
  if (set === "empty") return null;
  const timeline: ForecastPoint[] = [];
  let balance = 2400;
  const events: Record<number, { income?: number; expenses?: number; label: string }> =
    set === "sparse"
      ? { 5: { expenses: 1450, label: "Rent" }, 12: { income: 3200, label: "Paycheck" } }
      : {
          2: { expenses: 90, label: "Utilities" },
          5: { expenses: 1450, label: "Rent" },
          8: { income: 3200, label: "Paycheck" },
          11: { expenses: 220, label: "Phone + internet" },
          15: { expenses: 60, label: "Streaming" },
          18: { expenses: 540, label: "Card payment" },
          22: { income: 3200, label: "Paycheck" },
          26: { expenses: 130, label: "Insurance" },
        };
  for (let i = 1; i <= 30; i++) {
    const e = events[i];
    const income = e?.income ?? 0;
    const expenses = e?.expenses ?? 0;
    balance += income - expenses;
    timeline.push({
      date: dayOffset(i),
      balance,
      change: income - expenses,
      income: income || undefined,
      expenses: expenses || undefined,
      label: e?.label ?? "",
    });
  }
  return {
    horizon_start: dayOffset(0),
    horizon_end: dayOffset(30),
    starting_balance: 2400,
    ending_balance: balance,
    lowest_balance: Math.min(...timeline.map((p) => p.balance)),
    lowest_date: dayOffset(5),
    total_projected_expenses: 0,
    total_projected_income: 0,
    will_go_negative: false,
    timeline,
  };
}

function buildNotifications(set: Dataset): { notifications: Notification[]; unreadCount: number } {
  if (set === "empty") return { notifications: [], unreadCount: 0 };
  const base: Notification[] = [
    { id: 1, type: "budget_overrun", title: "Food budget exceeded", message: "You've spent $612 of your $500 Food budget this month.", read: false, created_at: dayOffset(0) + "T09:12:00" },
    { id: 2, type: "anomaly", title: "Unusual charge spotted", message: "A $148 charge at ACME HARDWARE is larger than your typical spend there.", read: false, created_at: dayOffset(0) + "T08:01:00" },
    { id: 3, type: "anomaly", title: "Subscription price rose", message: "STREAMVAULT went from $11.99 to $15.99 this cycle.", read: false, created_at: dayOffset(-1) + "T19:30:00" },
    { id: 4, type: "budget_overrun", title: "Transport near limit", message: "You're at 92% of your Transport budget with 9 days to go.", read: true, created_at: dayOffset(-3) + "T12:00:00" },
    { id: 5, type: "info", title: "Statement imported", message: "We reconciled 41 transactions from your June statement.", read: true, created_at: dayOffset(-5) + "T07:45:00" },
  ];
  const list = set === "sparse" ? base.slice(0, 2) : base;
  return { notifications: list, unreadCount: list.filter((n) => !n.read).length };
}

function seed(set: Dataset) {
  const { notifications, unreadCount } = buildNotifications(set);
  useStore.setState({
    isLoggedIn: true,
    userLoaded: true,
    taxFeaturesEnabled: true, // so the deck shows the Tax destination
    recentTransactions: buildTransactions(set),
    forecast: buildForecast(set),
    forecastLoaded: true,
    notifications,
    unreadCount,
    notificationsLoaded: true,
  });
}

export default function DevPreview() {
  const [dataset, setDataset] = useState<Dataset>("rich");
  const [surface, setSurface] = useState<Surface>("timeline");
  const [dark, setDark] = useState(false);
  const [deckOpen, setDeckOpen] = useState(false);

  // Seed SYNCHRONOUSLY on first render — before any child mounts — so children
  // see forecastLoaded=true and never race a fetch (TimelineCard's effect runs
  // before this component's effects, child-before-parent).
  const booted = useRef(false);
  if (!booted.current) {
    booted.current = true;
    seed("rich");
  }

  // Neutralise backend GETs against a dead :8000. A never-resolving promise lets
  // the components mount and poll without their .then() ever clobbering the
  // seeded fixtures (the store fetchers set state on success — a real response,
  // even an empty one, would overwrite our seed). Seeded state simply stands.
  useEffect(() => {
    const orig = api.get.bind(api);
    (api as unknown as { get: typeof api.get }).get = ((url: string, ...rest: unknown[]) =>
      url.startsWith("/notifications") || url.startsWith("/forecast")
        ? new Promise(() => {})
        : (orig as (...a: unknown[]) => Promise<unknown>)(url, ...rest)) as typeof api.get;
    (window as unknown as { __useStore: typeof useStore }).__useStore = useStore;
    return () => {
      (api as unknown as { get: typeof api.get }).get = orig;
    };
  }, []);

  useEffect(() => seed(dataset), [dataset]);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  const btn = (active: boolean) =>
    `rounded-none border px-3 py-1 text-xs uppercase tracking-[0.18em] transition-colors ${
      active ? "border-gold bg-gold/15 text-foreground" : "border-rule-strong/40 text-muted-foreground"
    }`;

  return (
    <div className="min-h-screen bg-background p-8 text-foreground">
      <div className="mx-auto max-w-2xl space-y-6">
        <div className="flex flex-wrap items-center gap-2 border-b border-rule-strong/30 pb-4">
          <span className="dept-label mr-2">Dev Preview</span>
          {(["timeline", "notifications", "deck", "chronicler"] as Surface[]).map((s) => (
            <button key={s} className={btn(surface === s)} onClick={() => setSurface(s)}>
              {s}
            </button>
          ))}
          <span className="mx-2 h-4 w-px bg-rule-strong/40" />
          {(["rich", "sparse", "empty"] as Dataset[]).map((d) => (
            <button key={d} className={btn(dataset === d)} onClick={() => setDataset(d)}>
              {d}
            </button>
          ))}
          <span className="mx-2 h-4 w-px bg-rule-strong/40" />
          <button className={btn(dark)} onClick={() => setDark((v) => !v)}>
            {dark ? "dark" : "light"}
          </button>
        </div>

        {surface === "timeline" && <TimelineCard />}
        {surface === "notifications" && (
          <div className="flex justify-end">
            <NotificationBell />
          </div>
        )}
        {surface === "deck" && (
          <div className="space-y-3">
            <button className={btn(false)} onClick={() => setDeckOpen(true)}>
              Open ⌘K deck
            </button>
            <p className="font-sans text-xs text-muted-foreground">
              Opens the Command Deck. Destination/action rows navigate (which
              leaves the harness); use it to inspect the list, filtering, keyboard
              nav, and the agent reply shell. (No backend here, so an agent ask
              just shows the "considering…" state.)
            </p>
            <CommandDeck
              open={deckOpen}
              onOpenChange={setDeckOpen}
              onConnectBank={() => alert("link bank (harness no-op)")}
              canConnectBank
            />
          </div>
        )}
        {surface === "chronicler" && (
          <div className="space-y-3">
            <p className="font-sans text-xs text-muted-foreground">
              The Chronicler drawer (the `/` key surface) opens from the right.
              Sending needs the backend; the header, empty state, canned chips and
              input render here. Game mode is off, so the title reads "Assistant".
            </p>
            <ChroniclerDrawer defaultOpen />
          </div>
        )}
      </div>
    </div>
  );
}
