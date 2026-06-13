# Step 08 — Plaid integrity

## Goal
Make Plaid sync correct and secure: encrypt the access token at rest, route each transaction to the
right local account, make dedup race-safe with a real unique constraint, refresh balances on sync,
and actually run the rule engine on synced transactions (the comment claims it does; it doesn't).

## Why it matters (user impact)
- **Plaintext bank token = a copied DB file is full read access to the user's bank.** Their own
  app tokens are SHA-256 hashed; the Plaid access token sitting in cleartext is the weakest link in
  the whole system for the most sensitive credential.
- **Multi-account institutions:** a single Plaid item often spans checking + savings + a card. If
  every transaction lands in one local account, the user's per-account balances and category views
  are wrong from day one — exactly the data they linked the bank to get right.
- **Stale balances:** if sync never updates balances, every forecast and Safe-to-Spend number runs
  off the balance captured at link time, *forever*. The user thinks the app is live; it's frozen.
- **Rules silently skipped:** the user sets up automation ("categorize Starbucks as Coffee",
  "round-up to savings") and it never fires on bank-synced transactions — the automation engine
  quietly skips ~all of a Plaid user's activity, contradicting the in-code comment.
- **Dedup race:** concurrent sync kicks (no in-progress guard) plus check-then-insert can duplicate
  rows, so the ledger double-counts spending.

## Findings closed (with evidence)
- **Plaintext token:** `db/models.py:174` stores `Token.key` (the Plaid access token) as a plain
  `String`; compare `RefreshToken.token_hash`.
- **One item → one account:** `plaid_service.py:121-147` (`_resolve_account_for_token`) maps the
  whole token to a single local account by **name**; `sync_token:158-162` passes that one
  `account_id` to every added/modified/removed row — per-transaction `account_id` is ignored.
- **No unique constraint:** `db/models.py:131/152` — `plaid_transaction_id` has no unique index;
  dedup is check-then-insert (TOCTOU).
- **Balances never updated:** `sync_token:135-179` never writes `Account.balance`.
- **Rules never run on sync:** `sync_token` adds rows directly and never calls `RuleEngine`
  (contrast `transaction_service.py:191`, which does run rules on manual entry).
- **One bad token aborts all (MEDIUM):** report notes a single token failure rolls back every
  token's sync; isolate per-token.

## Preconditions
- A symmetric key for token encryption (env-provided; reuse a settings secret or a dedicated
  `plaid_token_key`). Confirm `cryptography`/Fernet is available, else use the stdlib path already
  in the project.
- Account↔Plaid-account mapping needs a column or table: at exchange time we know each Plaid
  `account_id`. Add a `plaid_account_id` to the local `Account` (or a join table) so routing is by
  id, not name.

## Implementation
1. **Encrypt `Token.key` at rest.** Wrap storage/read with encrypt/decrypt (Fernet). On exchange
   (`routers/plaid.py::exchange_public_token`), encrypt before `TokenORM(key=...)`; in
   `plaid_service`, decrypt right before calling Plaid. Provide a one-shot migration to encrypt
   existing rows (single-user: a handful). Never log the decrypted token.
2. **Per-transaction account routing.** At exchange time, create/lap one local `Account` per Plaid
   account and store its `plaid_account_id`. In `sync_token`, resolve each transaction's local
   account from the transaction's own `account_id` (build a `{plaid_account_id: local_id}` map
   once), instead of a single `account_id`. Stop keying by name (fixes the rename-breaks-sync and
   duplicate-name-crash findings).
   - **⚠ Update the transfer guard (cross-ref Step 06).** Removing name-keying breaks
     `_is_plaid_managed` (`accounts.py:165-174`), which the Step 06 transfer endpoint relies on to
     refuse transfers into/out of Plaid-synced accounts. When `plaid_account_id` exists, rewrite the
     guard to `Account.plaid_account_id IS NOT NULL` (or join the new mapping) instead of matching
     `TokenORM.name == account.name`. Add/adjust a transfer test
     (`test_transfer_plaid_account_422`) so it still passes after de-name-keying.
3. **Race-safe dedup — exact constraint, no migration footgun.** `plaid_transaction_id` is
   **nullable** and lives in **two tables** (`Expense`, `Income` — `models.py:131,152`); a naive
   single-column UNIQUE is wrong (it must not collide manual rows where the column is NULL). Specify
   it precisely:
   - A **partial UNIQUE index** on **each** table:
     `CREATE UNIQUE INDEX uq_expense_plaid_txn ON expenses(plaid_transaction_id)
      WHERE plaid_transaction_id IS NOT NULL;` and the equivalent on `incomes`. SQLite supports
     partial indexes; NULLs are excluded so manual rows are unaffected. A Plaid transaction id is
     globally unique per item, so the single-column partial index suffices; if account scoping is
     judged necessary after the routing change, include `account_id` and document why.
   - An **Alembic migration** that **first de-duplicates existing rows** (the current
     check-then-insert may already have produced duplicates) **before** creating the index, so the
     migration can't fail on current data. On the in-memory test DB, `create_all` builds the index
     from the model definition.
   - Replace check-then-insert with insert + `except IntegrityError: db.rollback(); skip`.
   - Add an **in-progress guard** (a per-token flag/row or advisory lock) so two concurrent sync
     kicks don't both process the same cursor batch.
4. **Refresh balances on sync.** After applying transactions, fetch the item's balances
   (`get_balance`) and update each mapped local `Account.balance` (atomic UPDATE per Step 06).
5. **Run rules on synced transactions.** After inserting each added/modified row and flushing for
   an id, call the same `RuleEngine(self.db).run_on_transaction(...)` path manual entry uses, with
   the synced row's fields. Idempotency: the rule engine's firing log already prevents double-fire
   on re-sync — verify and rely on it.
6. **Isolate per-token failures.** Wrap each token's `sync_token` in its own try/except so one
   `ITEM_LOGIN_REQUIRED`/network error doesn't roll back the others; log + (stretch) flag the item
   as needing re-auth for the UI.

## Tests to add (`server/tests/test_plaid_sync.py`, `test_rule_engine.py`)
- `test_access_token_encrypted_at_rest`: after exchange, the stored `Token.key` ciphertext ≠ the
  Plaid access token, and the service round-trips it to the original for API calls.
- `test_multi_account_item_routes_by_account_id`: a synced batch spanning two Plaid accounts lands
  in the two correct local accounts (not all in one).
- `test_duplicate_plaid_transaction_id_is_noop`: syncing the same `plaid_transaction_id` twice
  yields one row (IntegrityError path), and the balance isn't double-applied.
- `test_sync_updates_account_balance`: after sync, the local balance equals Plaid's reported
  balance.
- `test_rule_fires_on_synced_transaction`: a category rule applied to a manual txn also fires on a
  matching synced txn.
- `test_one_failing_token_does_not_abort_others`: two tokens, the first raises; the second still
  syncs and commits.
- `test_renamed_account_still_syncs`: rename a local account; sync still routes by `plaid_account_id`
  (no name dependency).

## User-centric & edge-case checks
- Institutions returning **zero accounts** still handled (existing guard at exchange) — no crash.
- A user who **renames** an account in the UI keeps syncing (the old name-keyed link would have
  silently died).
- **Re-link / re-sync** doesn't duplicate history or double-count spend (unique constraint +
  idempotent rules).
- A bank requiring re-auth (`ITEM_LOGIN_REQUIRED`) degrades to "this account needs reconnecting"
  rather than breaking every other linked bank's sync.
- Balances the user sees after a sync match their bank app — the whole point of linking.

## Regression guardrails
- The sign convention (Plaid `amount>0` → Expense, `<0` → Income; `plaid_client.py`) is preserved.
- Game-event drafts still recorded in the same transaction (`sync_token:153-174`) — don't break the
  fold-with-apply law; rule firing and event recording both inside the sync transaction.
- Run `pytest -q server/tests/test_plaid_sync.py server/tests/test_rule_engine.py
  server/tests/test_categorization.py`.

## Done-when
- [ ] Plaid access token encrypted at rest; never logged in cleartext.
- [ ] Transactions route to the correct local account by Plaid `account_id`.
- [ ] Unique constraint + IntegrityError dedup + in-progress guard; no duplicate rows.
- [ ] Balances refresh on sync; rules fire on synced transactions.
- [ ] One token's failure can't abort the others; Plaid + rule tests green.