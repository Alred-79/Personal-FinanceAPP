# Step 10 — Client correctness

## Goal
Fix the client cluster that most directly degrades the user's day-to-day experience: timezone
off-by-one bugs, app-wide swallowed errors, the fire-and-forget transaction dialog, financial state
surviving logout, the Plaid Link race, in-render mutation, and missing request cancellation.

## Why it matters (user impact)
- **Timezone bugs** make dates *wrong on screen*: a transaction the user enters "today" can show
  yesterday/tomorrow, the calendar highlights the wrong day, the weekly window is off, goal
  deadlines shift a day. For a finance app, a transaction on the wrong date is a real correctness
  failure, not cosmetic.
- **Swallowed errors** mean a backend outage renders as innocent empty states ("Nothing to project
  yet"), and a failed save looks like a success. The user makes decisions on data that silently
  failed to load or save. **The fire-and-forget TransactionDialog is the worst case: on a server
  error the dialog closes and the form clears, so the user believes the transaction saved when it
  didn't.**
- **State leaking across logout** (next "user" — or the same user re-logging in — seeing the prior
  session's Safe-to-Spend / budget / selected account) is both a privacy smell and a correctness
  bug.
- **Plaid Link race** can brick the Connect button (script not loaded yet), and unhandled exchange
  failures leave the user stuck with no feedback.

## Findings closed (with evidence)
- **Timezone:** `client/src/lib/dates.ts:9-10` serializes local dates via `toISOString()` (UTC);
  the report lists `new Date("YYYY-MM-DD")` (UTC midnight), goal deadlines, transaction-dialog
  default, calendar today-highlight, timeline past/future split — all UTC-based. One shared helper
  fixes ~8 sites.
- **Logout leaves financial state:** `store.ts:659-690` resets many slices but **not**
  `safeToSpend`, `s2sPrefs`, `budgetAllotment`, or `selectedAccountId`; game mode (`gameMode.tsx`)
  fetches once on mount and never resets.
- **Errors swallowed:** dozens of `console.error`-only catch blocks in `store.ts`; rethrowing
  actions (`deleteAccount`, `addGoal`, `fetchLinkToken` at `:699-702`, …) called without catch.
- **Fire-and-forget dialog:** `TransactionDialog.tsx` calls `onSubmit()` then immediately
  `setOpen(false)` + clears the form without awaiting/handling errors.
- **In-render mutation:** `Accounts.tsx:116` `.sort()` mutates store state during render.
- **Plaid Link race / no destroy:** `PlaidConnect.tsx` + `AppShell.tsx` call `window.Plaid.create()`
  with no load guard and never `.destroy()`; exchange failures unhandled.
- **No AbortController** anywhere (grep: 0 hits) → stale responses can overwrite fresh ones.
- **Coupled to Step 03:** `store.ts:697` still calls `/plaid/link-token/?user_id=${user.id}` — Step
  03 removes that param, so this call **must** change to the authed no-param form or it breaks.

## Preconditions
- The toast system (`hooks/useToast.ts`, `components/ui/toast.tsx`) exists — reuse it for error
  surfacing (don't invent a new mechanism).
- Step 03 merged (link-token is authed/no-param) so the `fetchLinkToken` change lands consistently.

## Implementation
1. **Shared local-date helpers** (`client/src/lib/dates.ts`):
   ```ts
   export const toLocalISODate = (d: Date): string => {
     const y = d.getFullYear(); const m = `${d.getMonth()+1}`.padStart(2,"0");
     const day = `${d.getDate()}`.padStart(2,"0"); return `${y}-${m}-${day}`;
   };
   export const parseLocalISODate = (s: string): Date => {
     const [y,m,d] = s.split("-").map(Number); return new Date(y, m-1, d);
   };
   export const todayLocalISO = () => toLocalISODate(new Date());
   ```
   Rewrite `currentWeekRange` to use `toLocalISODate`. Route the other sites through these:
   transaction-dialog default date, calendar today-highlight, timeline past/future split, goal
   deadline parsing. Replace `new Date("YYYY-MM-DD")` with `parseLocalISODate`.
2. **Reset all state on logout** (`store.ts:661-689`): add `safeToSpend: null`, reset `s2sPrefs` to
   its initial value, `budgetAllotment: <initial>`, `selectedAccountId: "all"`. Reset game mode in
   `gameMode.tsx` on logout (export a `reset()` or subscribe to `isLoggedIn`). Verify no slice in
   the store's initial state is missed (consider a single `initialState` object reused by logout).
3. **Surface errors** (`store.ts`): give the main domains an error field (or reuse toast) so a
   fetch failure shows a toast / inline error instead of a silent empty state. At call sites that
   invoke rethrowing actions, wrap in try/catch and toast the failure (no unhandled rejections).
   Fix `fetchLinkToken` to the authed form: `api.get("/plaid/link-token/")` (no `user_id`).
4. **TransactionDialog is await-and-handle** (`TransactionDialog.tsx`): `await onSubmit()` inside a
   try; only on success `setOpen(false)` + clear the form; on error keep the dialog open, keep the
   form populated, and toast the failure. Add a submitting flag to disable the button (double-submit
   guard).
5. **Non-mutating sort** (`Accounts.tsx:116`): `[...txns].sort(...)`.
6. **Plaid Link robustness** (`PlaidConnect.tsx`, `AppShell.tsx`): guard `window.Plaid` existence /
   script load before `create()` (render a disabled/loading Connect until ready); keep the handler
   in a ref and `.destroy()` it in the effect cleanup; wrap `exchangePublicToken` in try/catch with
   a toast on failure.
7. **AbortController** in racy fetchers (search, pagination, forecast-horizon): create a controller
   per request, abort the previous on a new call, ignore `AbortError`, so a slow stale response
   can't overwrite a fresh one.

## Tests to add (`client/src/__tests__`, vitest)
- `lib/dates.test.ts`: with a mocked timezone (e.g. set TZ to `America/Los_Angeles` and to a
  positive-offset zone), `toLocalISODate(new Date(2026,5,12))` → `"2026-06-12"` (no UTC shift);
  `parseLocalISODate("2026-06-12").getDate() === 12`; `currentWeekRange` boundaries are local.
- `store/store.test.ts`: after `logout()`, `safeToSpend`, `s2sPrefs`, `budgetAllotment`,
  `selectedAccountId` are back to initial; game mode reset.
- A `TransactionDialog` test: with `onSubmit` rejecting, the dialog **stays open**, the form keeps
  its values, a toast fires, and the submit button re-enables.
- An `Accounts` test asserting the source array isn't mutated by render (sort produces a new array).
- A Plaid test: Connect is disabled until `window.Plaid` is present; an exchange failure surfaces a
  toast (not a silent stuck state).
- A fetcher test: firing two searches, the first's late resolution does not overwrite the second's
  result (AbortController).

## User-centric & edge-case checks
- A user in **UTC-5** and a user in **UTC+9** both see the date they actually picked — test both
  offset directions and the midnight boundary.
- A failed save **never** looks like a success: the dialog staying open with the data intact is the
  signal that lets the user retry instead of losing the entry.
- Logging out then back in (same machine) shows a clean slate — no prior Safe-to-Spend flashing
  before refresh.
- Connect button isn't dead on a slow network (script still loading) — it shows a loading state,
  then becomes active.
- Rapid typing in search doesn't show flickering stale results.
- Receipt upload: `capture="environment"` blocks gallery uploads — relax to allow gallery if in
  scope (otherwise note for backlog).

## Regression guardrails
- The toast system is reused, not replaced; existing components that already handle errors keep
  working.
- The `fetchLinkToken` change is **required** by Step 03 — verify the connect flow end-to-end after
  both land.
- Run `cd Personal-FinanceAPP && npx vitest run` (focus: `lib/dates.test.ts`, `store/store.test.ts`,
  `components/CashflowCalendar.test.tsx`, `components/TimelineCard.test.tsx`,
  `components/TransactionsCard.test.tsx`).

## Done-when
- [ ] One shared local-date helper; all ~8 timezone sites routed through it; dates test passes in
      multiple zones.
- [ ] Logout resets financial + game state to initial.
- [ ] Errors surface via toast/error state; no silent empty states; no unhandled rejections.
- [ ] TransactionDialog awaits, keeps the dialog open + data on failure, guards double-submit.
- [ ] Non-mutating sort; Plaid Link guarded + cleaned up + exchange errors handled; `fetchLinkToken`
      uses the authed no-param endpoint.
- [ ] AbortController in racy fetchers; vitest green.

---

## Out of scope this pass (follow-up backlog)
**Low-severity:** frozen `Account.last_updated` import-time default; refresh-token table pruning;
bcrypt 72-byte truncation guard; roundup firing on refunds/income; `%Y-W%W` non-ISO week buckets;
MCP `ttl_days` overflow 500; receipt content-type trusted (no magic-byte sniff); `verbose=True`
agent dumping prompts to stdout; assorted dead code (Ascension tiers, WardEarned, reachable_at
tautology); client debounce-timer leak, index keys, aria-live spam, hover-only delete buttons,
no-confirm account delete, sendBeacon wiping assistant history, `apiBase` LAN/port heuristic,
module-level `today` staleness, missing SheetTitle, clickable divs without keyboard semantics.

**Refactors (deliberately deferred — large, quality-only):** decompose `assistant_service.py`
(1113 lines) and `store.ts` (921 lines); dedup the row→dict serializers, date-window sum queries,
and event-log scans; dependency-free game `registry.py` to replace the import-order shims; a shared
idempotency-key builder everywhere (partially started in Step 09).

**Production guardrails (recommended next project):** security headers (HSTS/CSP/X-Frame-Options);
gate `/docs` & `/openapi.json` in production; fail startup if `environment=production` with a
default secret or localhost in credentialed CORS; idempotency keys on all money-mutating POSTs;
structured JSON logs + request IDs + Sentry; timeouts/retry/backoff on Plaid/Groq/Tavily; Plaid
webhooks + `ITEM_LOGIN_REQUIRED` UX; a real SQLite backup strategy (`.backup`/Litestream).