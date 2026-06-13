# Step 04 — C5 assistant action safety

## Goal
Close **C5**: make `SUPPORTED_ACTIONS` the single, enforced source of truth so
`create_allocation` and `whatif_commit` (money-moving actions) can't be reached around the
allowlist; rate-limit the propose/confirm endpoints; and make the human-approval loop *real* in
the client (it is currently never called) or explicitly, visibly disabled.

## Why it matters (user impact)
- The whole write-safety story the backend tells — "the model proposes, the user approves, the
  server runs it" (`assistant_service.py:476`) — only protects the user if (a) the set of runnable
  actions is actually bounded and (b) the approval step exists in the UI. Today neither holds:
  `validate` runs 5 actions while the allowlist names 3, and **no client code calls
  `/actions/propose` or `/actions/confirm`** (verified — zero references in `client/src`). So the
  advertised safety gate is partly dead code.
- A user who trusts "the AI can't move my money without me confirming" deserves that to be true.
  Either the confirm UI exists and they see exactly what will change before it happens, or the
  write path is off and nothing silently fires.

## Findings closed (with evidence)
- **C5 allowlist bypass:** `assistant_service.py:478` lists 3 actions, but
  `ActionService.validate` returns successfully for `create_allocation` (`:616-627`) and
  `whatif_commit` (`:629-640`) *before* the `raise ActionError("Unsupported action")` fallback
  (`:642`). Both then execute. `SUPPORTED_ACTIONS` is never consulted in `validate` — it's dead.
- **Propose/confirm unthrottled:** `routers/assistant.py:63` (`propose_action`) and `:85`
  (`confirm_action`) have no `@limiter.limit`.
- **Approval loop unwired:** no `client/src` reference to either endpoint.

## Scope split — security fix vs. product feature (do not bundle)
This step contains two unrelated things that the original draft fused together. Keep them separate so
the security fix can ship without committing to a product direction:
- **Part A — C5 (security, ship now):** enforce the allowlist + anti-drift + rate-limit propose/
  confirm. This *closes the finding* and depends on nothing product-side. Items 1–3, 5.
- **Part B — approval UI (product bet, opt-in):** wiring a confirmation card in the client to make
  the (currently dead) write path user-reachable. This is **building a new user-facing feature**, not
  remediating a bug — the write path has been dead since it was written and no user has been blocked
  by its absence. Item 4. **Do Part B only if the product owner decides assistant-driven writes are
  on the roadmap.** If not, leave the endpoints dead-but-safe (Part A still applies: a dead endpoint
  must still reject unlisted actions) and mark Part B "deferred — product decision."

## Preconditions
- Step 02 merged (`settings.assistant_rate_limit`, proxy-aware limiter).
- Decide product intent: are `create_allocation` / `whatif_commit` *meant* to be usable?
  Default below = **No** (they were never wired). Flip only as a deliberate product call.
- Decide Part B intent: ship the approval UI, or leave the write path dead-but-safe? Part A does not
  wait on this answer.

## Implementation
1. **Enforce the allowlist at the top of `validate`** (`assistant_service.py::ActionService.validate`):
   ```python
   if action not in SUPPORTED_ACTIONS:
       raise ActionError(f"Unsupported action: {action}")
   ```
   Place it as the first statement so unknown/disabled actions 400 before any param coercion.
   Keep `SUPPORTED_ACTIONS = ("add_transaction", "add_goal", "recategorize_transaction")` (the two
   extras stay **out**). If product decides to support them, add them to `SUPPORTED_ACTIONS`
   *and* wire their UI — never one without the other.
2. **Single-source guarantee (anti-drift):** maintain an explicit module-level
   `_HANDLED = {"add_transaction", "add_goal", "recategorize_transaction", ...}` set listing every
   action `validate`/`execute` knows how to handle, and assert in a test that
   `_HANDLED == set(SUPPORTED_ACTIONS)`. (Do **not** AST-parse the method body for `if action ==`
   branches — that's brittle and breaks on refactors.) A dev adding a handler branch without
   updating both sets fails CI. Wire `validate` to dispatch off `_HANDLED` membership so the set is
   load-bearing, not decorative.
3. **Rate-limit propose/confirm** (`routers/assistant.py`): add
   `@limiter.limit(settings.assistant_rate_limit)` and `request: Request` to both
   `propose_action` and `confirm_action`. (Confirm is already replay-guarded by `reserve_jti`; the
   limit is about abuse/cost, not correctness.)
4. **(Part B — OPT-IN) Wire the approval loop in the client.** Build this **only if** the product
   owner has decided assistant-driven writes ship (see "Scope split"). If deferred, skip this item
   entirely — Part A already makes the path safe — and record "Part B deferred, write path
   dead-but-safe" in the completion. When building it, implement in
   `client/src/components/custom/AssistantInterface/AssistantInterface.tsx`:
   - When the assistant stream yields a proposal (the write "tool" returns action+params+summary),
     render a confirmation card showing the **human summary** and the concrete params, with
     **Approve** / **Dismiss**.
   - Approve → POST `/assistant/actions/confirm/` with the token; show success/failure via toast;
     refresh affected store slices (transactions/goals).
   - Add the API calls to `client/src/lib/api.ts` (or store) — there are none today.
   - **No Plaid involvement.** All three allowlisted actions (`add_transaction`, `add_goal`,
     `recategorize_transaction`) write to the **local** DB only; nothing is sent to Plaid/banks
     (Plaid is read-only inbound here — `databridge/plaid_client.py` requests only the
     `transactions` product). So this carries no money-transmission / Plaid-restriction risk.
   - **⚠ Local double-count guard:** `add_transaction` must **not** target a Plaid-synced account,
     or a manually-added "$5 Starbucks" will be duplicated when the next Plaid sync pulls the same
     row from the bank. Reuse the same guard the transfer endpoint uses
     (`_is_plaid_managed`, `accounts.py:165-174`; and after Step 08, the `plaid_account_id`-based
     check) — reject or warn when the chosen account is Plaid-managed. `add_goal` /
     `recategorize_transaction` are unaffected (recategorize relabels an existing row, doesn't
     create one).
     - **Cross-step coupling (06 ↔ 08):** this is the *same* guard Step 06's transfer relies on and
       Step 08 de-name-keys. Until Step 08 lands, the guard matches by name, so it will mis-classify
       a **renamed** Plaid account (treating it as manual) — `add_transaction` could then double-count
       on the renamed account. Land the strict guard here against the name-key, and let Step 08's
       `plaid_account_id` rewrite fix it everywhere at once. Add the Plaid-account rejection test
       (`test_add_transaction_rejects_plaid_account`) so Step 08's change is caught if it breaks it.
     - **Product reality:** with this guard, the assistant can only add transactions to
       **manually-managed** accounts — not to any account the user linked a bank to. For a user whose
       accounts are mostly Plaid-linked, "the assistant can log a transaction" is effectively
       unavailable. That's correct (it avoids double-counting), but it thins the value of Part B —
       another reason Part B is a deliberate product call, not a default. The assistant should
       *explain* this, not silently 422 (see edge-case checks).
5. **Don't leak internals in errors:** `ActionError` messages stay user-facing and short (they map
   to 400s in the router) — no stack traces or provider text.

## Tests to add (`server/tests/test_assistant_writes.py`)
- `test_validate_rejects_unlisted_actions`: `ActionService.validate("create_allocation", {...})`
  and `validate("whatif_commit", {...})` both raise `ActionError("Unsupported action: ...")`.
- `test_supported_actions_matches_handlers`: assert `_HANDLED == set(SUPPORTED_ACTIONS)` (the
  explicit-set anti-drift check; no AST parsing).
- `test_propose_unlisted_action_400`: POST `/assistant/actions/propose/` with
  `action="whatif_commit"` → 400 (via `client` fixture).
- `test_propose_confirm_happy_path`: propose `add_transaction` → token; confirm → the transaction
  exists and the balance moved (end-to-end through the real endpoints).
- `test_confirm_token_replay_409`: confirm the same token twice → second is 409 (existing
  `reserve_jti` behavior — pin it so we don't regress).
- `test_confirm_token_wrong_user_403`: token minted for user A, confirmed while authed as B → 403.
- `test_propose_rate_limited`: with `assistant_rate_limit="1/minute"` + the Step 02 `rate_limited`
  fixture (flip `limiter.enabled`, not the setting), 2nd propose → 429.
- `test_add_transaction_rejects_plaid_account`: proposing/confirming `add_transaction` against a
  Plaid-synced account is rejected (422) to prevent the sync double-count; a manual account works.

## Client tests — `client/src/__tests__` (Part B only — skip if Part B is deferred)
- A vitest that renders `AssistantInterface`, injects a proposal message, clicks **Approve**, and
  asserts a POST to `/assistant/actions/confirm/` with the token + a success toast.
- A test that **Dismiss** sends nothing and clears the card (no accidental writes).

## User-centric & edge-case checks
- The confirmation card shows the **summary string** the server already produces (e.g. "Set aside
  $40.00 toward goal #3") so the user reads plain English, not raw JSON, before approving.
- Double-click Approve must not double-write — the UI disables the button after the first click;
  the server's `reserve_jti` is the backstop (test the replay 409).
- An expired proposal token (10-min TTL) approved late → the user gets a clear "this suggestion
  expired, ask again," not a 500.
- Proposing a transaction on a Plaid-synced account → the assistant explains it can only add to
  manually-managed accounts (avoids the sync double-count), rather than silently 422-ing.

## Regression guardrails
- `add_transaction`/`add_goal`/`recategorize_transaction` still work end-to-end (don't over-tighten).
- Run `pytest -q server/tests/test_assistant_writes.py server/tests/test_assistant_security.py`.
- Client (only if Part B is built): `npx vitest run` for the assistant tests.

## Done-when
### Part A (security — always)
- [ ] `validate` rejects anything not in `SUPPORTED_ACTIONS`; anti-drift test green.
- [ ] propose/confirm rate-limited; replay + wrong-user still guarded.
- [ ] `add_transaction` refuses Plaid-synced accounts (no sync double-count); rejection test pins it
      so Step 08's de-name-keying can't silently break it.
- [ ] Server assistant tests green.
### Part B (approval UI — only if product opted in)
- [ ] Approval loop wired in the UI: proposal card → Approve → confirm; Dismiss writes nothing.
- [ ] Assistant explains the manual-account-only constraint instead of a silent 422.
- [ ] Client assistant tests green.
### If Part B deferred
- [ ] Recorded as "deferred — product decision"; write path is dead **but safe** (Part A holds).