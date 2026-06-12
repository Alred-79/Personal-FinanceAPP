# 01 — Preflight gate + the event substrate

> Implements v4 §3 (Law 1), §12 (backend blueprint). Everything later folds over what you build
> here. **This package is backend-only. No UI work.**

## Context recap

v4's architecture law: bank truth stays in the existing CRUD tables (synced by
`plaid_service`/`transaction_service`); an **append-only event log** is the source of truth for
the *game domain only*. Projections (player stats, boss state, streaks) fold over events
**synchronously, in the same DB transaction** that appends them — no async, no queues, no CQRS.
Pending transactions never become events. Corrections are new compensating events, never edits.

## Preconditions — THE v1 GATE (hard stop)

v4 depends on v1 deliverables. Verify each by reading code, not by trusting docs:

- [ ] `server/src/services/forecast_service.py` exposes a cashflow projection covering **income
      and expenses** (v1 calls it `project_cashflows`; the pre-v1 version projected expenses
      only). It must return dated future flows usable for "will balance go negative."
- [ ] A Safe-to-Spend computation exists server-side (v1: `safe_to_spend()`; pre-v1 there was
      only client-side `get_budget_allotment`).
- [ ] Rules engine exists: `Rule` and `RuleExecution` models are in `server/src/db/models.py`
      AND have applied Alembic migrations (check `alembic heads` / the live schema, not just the
      model file — the income `recurrence` column was historically defined-but-never-migrated).
- [ ] `RuleExecution` stores `amount_cents`, `action_type`, `fired_at` (v1 enabler).
- [ ] Rules support a generic target (`target_kind` + `target_id`), not only goals (v1 enabler —
      needed in package 06 for `pay_liability`).
- [ ] `notification_service.py` exists and can deliver an in-app notification.
- [ ] Identify the live SQLite file from app config (repo root contains `finance_tracker.db`;
      do NOT trust older docs that say `budget_ai.db`). Confirm it is on the local tree, not
      OneDrive.

**If ANY box fails: STOP. Report which. v1 must be completed first. Do not stub v1 features.**

## Out of scope (later packages)

Mode system (02), alerts (03), stats/XP semantics (04), any UI, any LLM call, `Liability` (06),
map generation (08). You build *plumbing* here, not features.

## Tasks

### 1. Migration A — core tables

New Alembic migration (additive only). Inspect `server/src/db/models.py` first; if a column
already exists under another name, adapt rather than duplicate.

```sql
CREATE TABLE game_events (
  id INTEGER PRIMARY KEY,                  -- rowid = global order (single writer)
  stream VARCHAR NOT NULL,                 -- 'player' | 'month:2026-06' | 'boss:<liability_id>' | 'sync'
  seq INTEGER NOT NULL,                    -- per-stream sequence, starts at 1
  type VARCHAR NOT NULL,                   -- 'XpAwarded.v1', 'TxnCorrected.v1', ...
  v INTEGER NOT NULL DEFAULT 1,
  payload TEXT NOT NULL,                   -- JSON, schema owned by the type
  idempotency_key VARCHAR UNIQUE,          -- nullable, but REQUIRED for any event derived from external data
  caused_by INTEGER REFERENCES game_events(id),
  created_at TEXT NOT NULL,
  UNIQUE(stream, seq)
);
CREATE TABLE projection_meta (
  name VARCHAR PRIMARY KEY, last_event_id INTEGER NOT NULL DEFAULT 0,
  rebuilt_at TEXT, status VARCHAR NOT NULL DEFAULT 'live'   -- 'live' | 'rebuilding'
);
CREATE TABLE llm_cache (
  cache_key VARCHAR PRIMARY KEY,           -- sha256(model|template_ver|input_hash|mode)
  kind VARCHAR NOT NULL, content TEXT NOT NULL, model VARCHAR NOT NULL,
  created_at TEXT NOT NULL, expires_at TEXT
);
```

Plus **append-only enforcement at the DB layer** (guardrail against future bugs):

```sql
CREATE TRIGGER game_events_no_update BEFORE UPDATE ON game_events
BEGIN SELECT RAISE(ABORT, 'game_events is append-only'); END;
CREATE TRIGGER game_events_no_delete BEFORE DELETE ON game_events
BEGIN SELECT RAISE(ABORT, 'game_events is append-only'); END;
```

### 2. Migration B — new columns on existing tables (only those used by 01–05)

- `users.game_mode VARCHAR NOT NULL DEFAULT 'off'` (`off|ambient|full`).
- `plaid_items.sync_cursor` **only if** sync bookkeeping doesn't already exist — inspect
  `plaid_service.py` first.
- A way to flag essential categories: if a categories table exists, add `essential BOOLEAN
  DEFAULT 0`; if categories are strings on transactions, create `category_settings(name PRIMARY
  KEY, essential BOOLEAN, user_confirmed BOOLEAN)`. Seed essentials: rent/mortgage, groceries,
  utilities, medical, insurance, childcare, debt-minimums.
- `transactions.worth_it VARCHAR NULL` (`'yes'|'no'`, used in 05/09 — cheap to add now).
- Do NOT add `liabilities` yet (package 06).

### 3. `server/src/services/game/` package

- `events.py`:
  - `record_events(session, events: list[GameEventDraft]) -> list[GameEvent]` — THE single write
    path. Computes per-stream `seq` (SELECT max under SQLite's write lock is safe — single
    writer), inserts with `INSERT OR IGNORE` semantics on `idempotency_key` (an ignored insert
    returns the pre-existing event and emits nothing downstream), then synchronously calls the
    fold registry for each *newly inserted* event, same session/transaction.
  - Event type registry: a dict `EVENT_TYPES = {"XpAwarded": 1, ...}` — `record_events` rejects
    unknown types (typo guard). Initial types: `BackfillSnapshot`, `SyncGapOpened`,
    `SyncGapClosed`, `TxnPosted`, `TxnCorrected`, `TxnReversed`, `MonthSealed`, `XpAwarded`.
- `folds.py`: `register_fold(projection_name, handler)`; handlers are pure
  `(state_row, event) -> mutations`. Ship one real projection now: `sync_state` (tracks open
  gaps + last posted txn per account) — small, proves the machinery.
- `upcasters.py`: `upcast(type, v, payload) -> payload` registry. Identity for v1 of everything;
  the seam must exist now.
- `clamp.py`: `clamped_xp_delta(true_delta) -> (applied, true)` — applied = `max(true_delta, 0)`.
  Every XP-touching fold MUST route through this. Payloads store both numbers.
- `rebuild.py` + entry point (`python -m src.services.game.rebuild <projection>|--all`):
  set status `rebuilding` → truncate projection rows → replay `game_events` ordered by `id`
  through upcasters + folds → update watermark → status `live`.

### 4. Sync-fold hooks (the Plaid mutability rules — v4 §12.3)

Find where transaction sync applies adds/modifies/removes (in `plaid_service.py` /
`transaction_service.py`). In the **same transaction** as the CRUD apply:

- **Posted txns only** → `TxnPosted.v1` with `idempotency_key='plaid:<txn_id>:posted'`.
  Pending transactions emit **nothing** (they will render as "fog" in package 08 — a UI state).
- **Modify after posted** → `TxnCorrected.v1 {caused_by, field_deltas}`. Folds consume deltas.
- **Remove after posted** → `TxnReversed.v1 {caused_by}` — compensation computed from the
  ORIGINAL event's payload, never from current projection state.
- **Sync failure / gap detected** → `SyncGapOpened.v1` / `SyncGapClosed.v1` per account; later
  packages must treat in-gap days leniently. Store gap bounds in payload.
- If the existing sync path can't distinguish pending→posted (no `pending_transaction_id`
  handling), fix the sync path first — additively.

### 5. Backfill + integrity harness

- One-off command emitting `BackfillSnapshot.v1` per stream (`player`, `sync`) capturing current
  derived state. **Never fabricate per-transaction history.**
- `server/tests/integrity.py` helper: `finance_tables_fingerprint(session) -> str` — a stable
  hash over all rows of accounts/transactions/budgets/goals/rules tables. Used by EVERY package:
  fingerprint → run game code → fingerprint → assert equal.

## Guardrails

- `record_events` is the only function that inserts into `game_events`. Add a grep-based test
  asserting no other call site uses the raw table.
- No game code imports write-capable helpers of financial services. Game services receive data
  via read queries only.
- Never raise to the user on a fold bug — log, skip, keep finance working (game layer is
  best-effort; finance layer is not).
- Don't refactor `plaid_service` beyond inserting the hooks. Resist cleanup urges.

## Test cases (`server/tests/test_game_substrate.py` + `test_game_sync_fold.py`)

Idempotency & append-only:
1. Same `idempotency_key` recorded twice → one row, fold ran once (projection value unchanged
   after second call).
2. Replaying an entire sync batch → zero new events, identical projections.
3. Raw `UPDATE`/`DELETE` on `game_events` → SQLite trigger aborts.
4. Unknown event type → `record_events` raises; nothing inserted.
5. Two streams interleaved → each gets contiguous `seq` 1..n; `UNIQUE(stream,seq)` holds.

Corrections & clamp:
6. `TxnPosted` (+$50 payment) then `TxnCorrected` (−$10) → projection reflects $40; both events
   present; correction's `caused_by` points at the original.
7. `TxnReversed` after a posted event → projection equals the state as if the original never
   happened (compute compensation from original payload — test with a projection that has since
   processed OTHER events, to prove no state-based shortcuts).
8. `clamped_xp_delta(-30)` → applied 0, true −30; a fold given a negative XP correction leaves
   XP unchanged and stores `{applied: 0, true: -30}` in the event payload.
9. XP-positive correction (+10) applies normally (clamp is one-sided).

Pending & gaps:
10. A pending transaction in a sync batch → zero events emitted.
11. Pending→posted (remove pending + add posted with `pending_transaction_id`) → exactly one
    `TxnPosted`, keyed by the POSTED txn id.
12. `SyncGapOpened` then `SyncGapClosed` → `sync_state` projection records the gap interval.

Rebuild & determinism:
13. Property-style: generate 200 random valid events (mixed types/streams, some corrections) →
    fold live; rebuild from scratch → projections byte-identical.
14. Rebuild with a registered upcaster (fixture `TestEvt.v1`→`v2`) → old payloads upcast, fold
    consumes v2 shape, stored rows untouched.
15. `projection_meta.last_event_id` watermark equals max folded id after live folds and after
    rebuild; status round-trips `rebuilding`→`live`.
16. Fold handler that raises → event row still committed, error logged, finance request path
    unaffected (simulate within a request-shaped transaction).

Integrity & migrations:
17. `finance_tables_fingerprint` unchanged across: recording 50 game events, a rebuild, a
    backfill snapshot.
18. Alembic upgrade→downgrade→upgrade round-trips on a scratch DB (downgrade may drop the new
    tables; it must never touch existing ones).
19. Backfill emits exactly one `BackfillSnapshot` per stream; running it twice doesn't duplicate
    (idempotency key `backfill:<stream>`).
20. Grep test: `game_events` table name appears in inserts only inside `events.py`.

## Exit criteria

- [ ] All 20 test groups above pass; full pre-existing suite passes.
- [ ] v1 gate boxes all checked and noted in the handoff.
- [ ] `python -m src.services.game.rebuild --all` runs clean on the dev DB.
- [ ] WAL pragmas confirmed (`journal_mode=WAL`, `busy_timeout`); DB confirmed local-tree.
- [ ] Handoff note appended below.

---
*Handoff notes (filled by the executing agent):*
