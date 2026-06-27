import { useMemo, useState } from "react";
import { dollars, dollarsCents } from "./gameData";
import { WATCH_SUBS, creepPct } from "./arcadeData";

/**
 * Subscription Watch — the REAL recurring-charge detector, made playable. It
 * lists the charges the app tracks, flags the ones that quietly raised their
 * price (+15% creep, habit_monsters.py) or sit unused, and totals the yearly
 * cost. Cancel rows to watch the annual figure fall. No timer, no whack-a-mole;
 * the value is the visibility, not the reflex.
 */
export function SubscriptionWatch() {
  const [cancelled, setCancelled] = useState<Set<string>>(new Set());

  const toggle = (name: string) =>
    setCancelled((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  const { monthlyKept, savedYear, creepCount, silentCount } = useMemo(() => {
    let kept = 0;
    let savedMonthly = 0;
    let creep = 0;
    let silent = 0;
    for (const s of WATCH_SUBS) {
      if (creepPct(s) != null) creep += 1;
      if (s.silent) silent += 1;
      if (cancelled.has(s.name)) savedMonthly += s.cents;
      else kept += s.cents;
    }
    return {
      monthlyKept: kept,
      savedYear: savedMonthly * 12,
      creepCount: creep,
      silentCount: silent,
    };
  }, [cancelled]);

  return (
    <div className="arc-game arc-watch">
      <div className="arc-watch__intro">
        <p className="arc-boss__lead">What this shows you</p>
        <p className="arc-boss__caption">
          The app watches every recurring charge, flags the ones that quietly raised their price or
          you’ve stopped using, and totals the yearly cost. Cancel a few to see what you’d keep.
        </p>
      </div>

      <div className="arc-watch__hud">
        <span>
          <b className="figure ledger-figures">{WATCH_SUBS.length}</b> charges found
        </span>
        <span>
          <b className="ink-debit figure ledger-figures">{dollars(monthlyKept)}</b>/mo ·{" "}
          <b className="ink-debit figure ledger-figures">{dollars(monthlyKept * 12)}</b>/yr
        </span>
      </div>

      <ul className="arc-watch__list">
        {WATCH_SUBS.map((s) => {
          const creep = creepPct(s);
          const off = cancelled.has(s.name);
          return (
            <li key={s.name} className={`arc-watch__row ${off ? "is-off" : ""}`}>
              <span className="arc-watch__id">
                <span className="arc-watch__name">{s.name}</span>
                <span className="arc-watch__cat">{s.category}</span>
              </span>
              <span className="arc-watch__amt figure ledger-figures ink-debit">
                {dollarsCents(s.cents)}/mo
              </span>
              <button
                type="button"
                className="arc-watch__act"
                aria-pressed={off}
                onClick={() => toggle(s.name)}
              >
                {off ? "keep" : "cancel"}
              </button>
              {(creep != null || s.silent) && (
                <span className="arc-watch__flags">
                  {creep != null && (
                    <span className="arc-badge arc-badge--creep">
                      ↑ {Math.round(creep * 100)}% from {dollarsCents(s.prevCents!)}
                    </span>
                  )}
                  {s.silent && <span className="arc-badge arc-badge--silent">unused 3mo+</span>}
                </span>
              )}
            </li>
          );
        })}
      </ul>

      <p className="arc-watch__save">
        {savedYear > 0 ? (
          <>
            You’d keep <b className="ink-credit figure ledger-figures">{dollars(savedYear)}</b> a year.
          </>
        ) : (
          <>
            <b className="ink-debit">{creepCount}</b> quietly raised their price ·{" "}
            <b className="ink-debit">{silentCount}</b> sit unused — start there.
          </>
        )}
      </p>

      <p className="arc-foot">price-creep flagged at +15% · this is the real subscriptions watch</p>
    </div>
  );
}
