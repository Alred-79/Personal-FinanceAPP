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

## Preconditions
- Step 02 merged (`settings.assistant_rate_limit`, proxy-aware limiter).
- Decide product intent: are `create_allocation` / `whatif_commit` *meant* to be usable?
  Default below = **No** (they were never wired). Flip only as a deliberate product call.

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
4. **Wire the approval loop in the client** (recommended path (a)) —
   `client/src/components/custom/AssistantInterface/AssistantInterface.tsx`:
   - When the assistant stream yields a proposal (the write "tool" returns action+params+summary),
     render a confirmation card showing the **human summary** and the concrete params, with
     **Approve** / **Dismiss**.
   - Approve → POST `/assistant/actions/confirm/` with the token; show success/failure via toast;
     refresh affected store slices (transactions/goals).
   - Add the API calls to `client/src/lib/api.ts` (or store) — there are none today.
   - Alternative path (b), if writes should stay off for now: add
     `settings.assistant_writes_enabled: bool = False`; when false, `propose_action` returns **403
     "Assistant writes are disabled"** so the dead path is explicit, not silently reachable via curl.
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
- `test_propose_rate_limited`: with `assistant_rate_limit="1/hour"` + limiter on, 2nd propose → 429.
- If path (b): `test_propose_disabled_returns_403` when `assistant_writes_enabled=False`.

## Client tests (if wiring path (a)) — `client/src/__tests__`
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
- If writes are disabled (path b), the assistant should *say* it can't make changes rather than
  silently proposing something that 403s.

## Regression guardrails
- `add_transaction`/`add_goal`/`recategorize_transaction` still work end-to-end (don't over-tighten).
- Run `pytest -q server/tests/test_assistant_writes.py server/tests/test_assistant_security.py`.
- If client wired: `npx vitest run` for the assistant tests.

## Done-when
- [ ] `validate` rejects anything not in `SUPPORTED_ACTIONS`; anti-drift test green.
- [ ] propose/confirm rate-limited; replay + wrong-user still guarded.
- [ ] Approval loop wired in the UI (path a) **or** writes explicitly 403'd (path b) — not silently
      reachable-but-unused.
- [ ] Server (and client, if path a) tests green.