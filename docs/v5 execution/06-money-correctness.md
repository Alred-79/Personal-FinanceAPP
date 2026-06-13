# Step 06 — Money correctness

## Goal
Make balance math race-safe and fix transfers, the assistant/MCP spend summary, budget rollover,
transaction pagination, and the budget allotment query. Money is the core promise of the app —
these are the bugs where the numbers can be quietly *wrong*.

## Why it matters (user impact)
- A finance app that loses a write under concurrency, or lets a transfer overdraw, or shows the
  assistant a *different* budget than the dashboard, erodes the one thing it must get right: the
  user trusting the numbers. Each fix below maps to a way the displayed money silently disagrees
  with reality.
- Transfers that move balances but leave **no transaction row** mean the ledger (the list the user
  scrolls) permanently disagrees with the account balances — the user sees money "missing" with no
  explanation, and the note they typed vanishes.

## Findings closed (with evidence)
1. **Lost-update / overdraft race:** balances mutate via `account.balance += …` on loaded ORM
   objects — `transaction_service.py:183` (create), `:239/:243/:248` (update), and the transfer at
   `routers/accounts.py:223-224`. The transfer's `if accounts["from"].balance < amount_cents`
   (`:219`) is a check-then-act TOCTOU → overdraft under concurrency.
2. **Transfers leave no ledger row + drop the note:** `routers/accounts.py:177-233` mutates
   balances and returns; `TransferIn.note` (`:162`) is validated then **never persisted**, and no
   Income/Expense/transfer row is written.
3. **Spend summary uses a fabricated user:** `read_queries.py:308-317` builds a bare `UserInDB`
   (no `savings_percent`) instead of loading the row — even though a correct loader exists right
   above at `read_queries.py:296-305`. So the assistant/MCP report a different budget than the UI.
4. **Budget rollover phantom surplus:** `budget_service.py:135-139` —
   `prior_remaining = base_limit - prior_spent`; for a budget's **first** month `prior_spent=0`, so
   it credits a full extra `base_limit` of rollover. Also it uses *this* budget's `base_limit` as
   "last month's limit."
5. **In-memory pagination:** the router's own `get_all_transactions`
   (`routers/transactions.py:58`, sort at `:124`) loads **all** income + expense rows, merges,
   sorts, and slices in Python (`:106-130`). A SQL-side helper `_paginated_transactions` exists
   (`read_queries.py:43`) and **already has 3 callers** (`:133, :163, :255`) — it is **not unused**.
   The fix is to make the router use that helper (or a shared variant), reconciling its filter
   signature (`q`, `category`, date/amount range, account-id ownership) with the helper's — see the
   regression note below; this is not a free "delegate to dead code" move.
6. **`get_budget_allotment`:** float dollar math, partial/nondeterministic SQLite `GROUP BY`,
   unclamped negative result (per report `budget_service`/spend path).
7. **Safe-to-Spend paycheck boundary:** re-verify whether `recurring.project_cashflows(user.id,
   as_of, horizon_end)` includes the anchoring paycheck on `horizon_end = next_pay`
   (`spend_service.py:180-204`). One earlier read said exclusive (FALSE), another said inclusive —
   **confirm against `recurring_service` bounds and fix only if inclusive.**

## Preconditions
- Integer-cents convention holds throughout (`money.py`); keep it.
- `get_db` wraps each request in one transaction (commit/rollback) — atomic UPDATEs run inside it.

## Implementation
1. **Atomic balance updates.** Replace `account.balance += delta` with an issued SQL UPDATE:
   ```python
   db.execute(
       update(AccountORM)
       .where(AccountORM.id == account_id)
       .values(balance=AccountORM.balance + delta, last_updated=func.now())
   )
   ```
   Apply in `transaction_service.create` (`:183`), `update` (`:239`, `:243`, `:248` — reverse/apply
   legs), and the transfer. Reload or `db.refresh` only where the new value is needed in the
   response.
2. **Transfer = atomic, guarded, recorded.** For the debit leg use a conditional UPDATE so the
   insufficient-funds check and the decrement are one statement (no TOCTOU):
   ```python
   res = db.execute(
       update(AccountORM)
       .where(AccountORM.id == from_id, AccountORM.balance >= amount_cents)
       .values(balance=AccountORM.balance - amount_cents, last_updated=func.now())
   )
   if res.rowcount == 0:
       raise HTTPException(422, "Insufficient balance")
   ```
   Then credit the destination. Persist a ledger record of the move **and the note** — either two
   linked rows (Expense on source / Income on destination, category "Transfer", carrying `note`) or
   a dedicated transfer row if the schema supports it. Choose the option that keeps the existing
   ledger views correct; document the choice. Consider an idempotency key on the POST (backlog
   pattern) so a double-submit can't double-transfer.
   - **⚠ Cross-step coupling with Step 08:** the transfer's Plaid-account guard calls
     `_is_plaid_managed` (`accounts.py:165-174`), which links Token↔Account **by name**. Step 08
     **removes name-keying** in favor of `plaid_account_id`. Step 06 lands first, so keep the
     name-based guard now — but **Step 08 must update this guard** to check `Account.plaid_account_id`
     (or the new mapping) when it de-name-keys, or transfers will wrongly allow/deny Plaid-synced
     accounts afterward. Cross-referenced in Step 08's implementation.
   - **⚠ Transient broken window between 06 and 08 — name it, don't ignore it.** In the interval
     after 06 lands (transfers now write real ledger rows and move balances) but before 08 de-name-
     keys, a user who has **renamed a Plaid-synced account** has a guard that no longer matches that
     account — so a transfer into it is wrongly *allowed*, and the moved amount then **double-counts**
     when the next sync pulls the bank's own rows. For a single-user app the blast radius is small,
     but it is a real regression window opened by 06's new ledger writes. Mitigation: land 06 and 08
     **together or back-to-back** (don't leave the window open across releases), and add a test that a
     renamed Plaid account is still detected as Plaid-managed (it will fail under 06's name-key and
     pass after 08 — useful as the canary that gates the window closed).
3. **Fix the spend summary user load** (`read_queries.py:308`): replace the fabricated `UserInDB`
   with the existing loader (the `:296-305` builder) so `savings_percent` matches the UI. Add a
   guard for "user not found."
4. **Budget rollover** (`budget_service.py:135-139`): only credit rollover when a prior budget
   period actually existed; for a brand-new budget, `prior_remaining = 0`. Use the *prior period's*
   limit (not this month's `base_limit`) as last month's limit when computing prior remaining.
5. **SQL-side pagination** (`routers/transactions.py::get_all_transactions`): replace the
   load-all-then-slice (`:106-130`) with a SQL UNION ALL + LIMIT/OFFSET + total count. **Reuse with
   care:** `_paginated_transactions` (`read_queries.py:43`) already does this shape but is **shared
   by 3 existing callers** (`:133, :163, :255`) — do **not** silently change its behavior. Either
   (a) extend `_paginated_transactions` to accept the router's full filter set (`q`, `category`,
   date/amount range, account-ids for ownership) with the new filters defaulting to no-op so the
   3 callers are unaffected, or (b) add a sibling helper for the richer filter case. Preserve the
   `{items, total, page, page_size}` response shape so the client is unaffected. The existing
   callers' tests (`test_read_queries.py`) must stay green either way.
6. **`get_budget_allotment`:** integer-cents math; fully-specified `GROUP BY` (include every
   non-aggregated column, e.g. add `recurrence`); clamp the final result at `max(0, …)`.
7. **Safe-to-Spend:** read `recurring_service.project_cashflows` bounds. If the upper bound is
   inclusive (`<= horizon_end`) it counts the paycheck landing on `next_pay` as income for *this*
   horizon, inflating spendable by a pay period — make the bound exclusive for the income leg (or
   subtract the boundary paycheck). If it's already exclusive, record "verified correct" and just
   add the pinning test.

## Tests to add
`server/tests/test_money.py`, `test_accounts.py`, `test_budget*.py`, `test_transactions.py`,
`test_read_queries.py`, `test_safe_to_spend.py` (use `db_session` for service-level, `client` for
endpoints):
- `test_balance_update_is_atomic`: two sequential create/update calls against the same account net
  to the correct sum (proves issued UPDATE, not stale read-modify-write).
- `test_transfer_rejects_overdraft`: transfer more than the source holds → 422 and **no** balance
  change on either account.
- `test_transfer_writes_ledger_and_note`: a transfer produces ledger record(s) carrying the note;
  the sum of visible transactions reconciles with the new balances.
- `test_transfer_same_account_422` and `test_transfer_plaid_account_422`: keep existing guards.
- `test_spend_summary_uses_real_savings_percent`: set the user's `savings_percent` to a non-default
  value; `query_spend_summary` reflects it (matches `SpendService` with the real user).
- `test_budget_first_month_no_phantom_rollover`: a brand-new rollover budget shows
  `effective_limit == monthly_limit` (no doubled surplus); a budget *with* a prior under-spent
  month does roll over correctly.
- `test_transactions_pagination_sql`: page 2 of a >page_size ledger returns the right slice and
  `total`; empty page and last partial page behave; filters still apply.
- `test_budget_allotment_non_negative_integer`: allotment is integer-cents, never negative, and
  deterministic across runs (no GROUP BY flakiness).
- `test_safe_to_spend_excludes_anchor_paycheck`: with a known next-pay date, spendable does **not**
  include the paycheck that lands on the horizon boundary.

## User-centric & edge-case checks
- Overdraft attempt gives a clear "Insufficient balance" — the user understands the transfer was
  refused, and **nothing** moved (atomicity), not a partial debit.
- The note the user typed appears on the resulting ledger entry (they can later recognize the
  transfer).
- The assistant's "you can safely spend $X" matches the dashboard's number to the cent — a mismatch
  reads as the app contradicting itself.
- New budget in its first month doesn't show a suspiciously doubled limit.
- Large ledgers paginate fast (SQL LIMIT) — no slow blank screen while the server loads everything.
- Transfer to/from the same account, zero/negative amounts (already blocked by `Field(gt=0)`), and
  amounts exactly equal to balance (allowed) all behave.

## Regression guardrails
- `money.py` rounding semantics unchanged; cents in, cents stored.
- Existing transaction create/update/delete tests still pass with issued UPDATEs.
- Run: `pytest -q server/tests/test_money.py server/tests/test_accounts.py
  server/tests/test_budget.py server/tests/test_budgets.py server/tests/test_transactions.py
  server/tests/test_read_queries.py server/tests/test_safe_to_spend.py
  server/tests/test_money_spine.py`.

## Done-when
- [ ] All balance mutations use issued atomic UPDATEs; transfer overdraft impossible.
- [ ] Transfers persist ledger rows + the note; balances reconcile with visible transactions.
- [ ] Spend summary uses the real user row; matches the UI.
- [ ] First-month rollover no longer doubles; prior-limit math correct.
- [ ] Transactions paginate in SQL; allotment integer/non-negative/deterministic.
- [ ] Safe-to-Spend paycheck boundary verified (and fixed if inclusive); all money tests green.