# Timezone / day-boundary audit

**Date:** 2026-06-14 · **Type:** read-only investigation (no code changed) · **Scope:** `server/src/`

## TL;DR

The classic "daily spending" timezone bug — a UTC *timestamp* mis-bucketed into the wrong local day — **does not exist here**, because the app never stores timestamps for financial dates. Every transaction/goal/snapshot date is a pure `YYYY-MM-DD` **string** (verified in the live DB: `'2026-06-10'`, no time component). Date bucketing (`strftime`) and all range filters are lexicographic string compares on date-only values, which are DST-immune.

The real, narrower exposure is: **the app has no per-user timezone.** Every "today" is the *server's* local date via `date.today()`. A user in Hawaii rolls over to a new day on the server's clock, not their own. This is consistent, already partly documented, and fine for a single-region single-user deployment — but it's the thing to fix first if multi-timezone users ever matter. Plus one small consistency nit (inclusive vs half-open end-of-range).

**Recommendation: do NOT undertake the full per-user-timezone change now.** The payoff is low for the current deployment and the change is cross-cutting. Fix the one cheap consistency nit; revisit the timezone column only if/when users span zones.

## What was checked

`date.today()` / `datetime.now()` / `func.current_timestamp()` call sites, `strftime` bucketing, all date range filters, the streak verdict's "today", Safe-to-Spend/forecast horizons, Plaid ingestion date assignment, and any timezone concept. ~45 sites reviewed.

## Findings by risk

### Foundational (good news)
- **Dates are date-only ISO strings.** `Expense.date` / `Income.date` / `Goal.date` / `BalanceSnapshot.date` are all `Mapped[str]` = `YYYY-MM-DD`. Confirmed against live data. No time, no zone → no UTC-vs-local mis-bucketing.
- **No per-user timezone anywhere.** No `timezone`/`ZoneInfo`/`pytz`/`tzinfo` column or setting. The whole app is server-local-date.

### STAMP-ONLY — low risk (~21 sites)
All `func.current_timestamp()` / `last_updated` writes (`db/models.py`, `accounts.py:285,297`, `transaction_service.py:60,68`, `plaid_service.py:208`, …) only *write* a creation/update time; nothing compares them against stored dates. No action.

### Bucketing & ranges — verified safe, with one nit
- `analytics.py:54` `func.strftime("%Y-%m" | "%Y-W%W" | "%Y-%m-%d", model.date)` — operates on date-only strings → deterministic, DST-free. **Safe.**
- `forecast_service.py:101-102` uses a correct **half-open** `[window_start, as_of)` for the burn window. **Good.**
- **NIT (consistency):** `analytics.py:69-71` and `transactions.py:37-39` filter the end of a range with `<= end` (**inclusive**), while the forecast window is half-open. Inclusive date-only ranges are *correct* (they include the whole end day), but the codebase mixes conventions. Low impact; worth standardizing on documented half-open `[start, nextday)` for any future range that ever carries a time component.

### Server-local "today" — the real exposure (~8 sites), all the same root cause
Every one of these resolves "today"/"as_of" to the server's local date and is otherwise correct *given that assumption*:
- `llm_budget.today_key()` (`:50`) — canonical budget day boundary; **already documented** server-local by design.
- streak verdict: `routers/game.py:209,232,273,…` pass `date.today()` into `daily.verdict_for_day` / `close_day`. GREEN/MISS hinges on which server-day "today" is.
- `spend_service.py:189` `as_of = as_of or date.today()` — Safe-to-Spend anchor.
- `scenario_service.py` drift checks; `scheduler.py` month/week close jobs (`CronTrigger` is **not** timezone-pinned).

**Consequence:** a call made after server-midnight but before the user's local midnight is "a day ahead" for that user (streak rollover, S2S anchor, budget reset). For a single-user/single-region app this is invisible. It only bites with users in other zones, or a server whose local zone observes DST while cron triggers aren't tz-aware.

### DST / scheduler
`scheduler.py` cron triggers (`CronTrigger(day=1, hour=0, minute=5)`, weekly Monday) are not timezone-anchored. Idempotency keys (`day:{user}:{date}`, `seal:{user}:{month}`) make a double-fire harmless, and the single-worker invariant is already a documented deploy precondition. So DST is a *latent* scheduling wobble, not a data-corruption risk.

## Recommendations (scoped, in priority order)

1. **Cheap now — standardize range convention + pin the scheduler tz.** Document half-open `[start, nextday)` as the house rule, and pass an explicit `timezone="UTC"` (or the chosen server zone) to the APScheduler `CronTrigger`s so DST can't shift a close job. ~1–2 small edits, no schema change, removes the only *unmitigated* item (DST wobble).
2. **Defer — per-user timezone (only if multi-zone users become real).** Add a nullable `user.timezone` (IANA), thread it into a single `today_for(user)` helper, and replace the ~8 `date.today()` boundary sites with it. This is the genuinely cross-cutting change; not worth it for the current single-region deployment. Scope it as its own task if/when the need is real.
3. **No action — bucketing/ingestion.** `strftime`, lexicographic compares, and Plaid's date-only `transaction.date` passthrough are correct as-is.

## Bottom line

The feared bug class isn't present (date-only storage saves it). The genuine gap is "no per-user timezone," which is consistent and acceptable for now. The only thing worth doing immediately is the tiny scheduler-tz + range-convention cleanup; the full timezone column is real but should stay deferred until there's a multi-zone user to justify it.
