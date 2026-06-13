# Step 01 — Single-user invariant + game re-scope

## Goal
Make "this is a single-user instance" an enforced, documented invariant rather than an unwritten
assumption. This re-scopes report finding **C1** (the entire game/event substrate is global, not
per-user) from a ~15-module rewrite + migration down to a guard plus documentation, because with
exactly one user a shared XP/streak/grace/boss/CategorySettings state is *correct behavior*, not a
cross-user leak.

## Why it matters (user impact)
- The owner never wants a stranger's signup to silently create a second account that then
  contends for the same global game state, or that can log in to *their* finances.
- If the app is ever shared (a link sent to a friend, deployed on a LAN per memory
  persfin-dual-tree-layout), an open `/signup/` is the difference between "nobody else can get in"
  and "anyone can mint an account." The guard is the cheapest possible protection.
- Future maintainers must know the game substrate's global keys are *intentional*, so nobody
  "fixes" it by half-adding `user_id` to some modules and creating split-brain projections.

## Findings closed (with evidence)
- **C1 (re-scoped):** `GameEvent` has no `user_id` (`server/src/db/models.py:467`); projection KV
  is keyed `(projection, key)` only (`server/src/services/game/folds.py:103-110`); event scans
  don't filter by user (`stats.py:210-216`); `CategorySettings` is global by schema
  (`models.py:532-546`). All **correct** under one user — we lock that in.
- **High "/signup/ has no rate limit"** is handled in Step 02; here we add the *count* guard.

## Preconditions
- Confirm exactly one user is expected. (User confirmed: "this is a one use user app.")
- `server/tests/conftest.py` creates users via the API/first signup — the guard must allow the
  *first* user through. Tests run with `rate_limit_enabled` off already.

## Implementation
1. **Settings** (`server/src/settings.py`): add
   ```python
   single_user: bool = True          # one-account instance; blocks a 2nd signup
   allow_signup: bool = True         # master switch; first signup still allowed when single_user
   ```
   Keep them in the `--- Auth and cookie hardening ---` block. Document that `single_user=True`
   means "registration closes after the first account."
2. **Signup guard** (`server/src/routers/auth.py::signup`): before `auth_service.create_user`,
   short-circuit when registration is closed:
   ```python
   if not settings.allow_signup:
       raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is disabled.")
   if settings.single_user:
       existing = db.execute(select(func.count(UserORM.id))).scalar_one()
       if existing >= 1:
           raise HTTPException(
               status.HTTP_409_CONFLICT,
               "Registration is closed (single-user instance).",
           )
   ```
   Import `func`, `UserORM`. Place the check first so we never hash a password for a doomed
   request (defends the bcrypt-CPU enumeration angle the report raised, before Step 02's limiter).
   The guard is gated on `settings.single_user` precisely so the test suite can disable it (see
   "Test impact" below) — do **not** hard-code it.
3. **Document the invariant** at the top of `server/src/services/game/__init__.py` (module
   docstring): game projections (XP/streak/grace/boss/homestead/CategorySettings) are deliberately
   global keys because the instance is single-user (Step 01); do **not** add per-user KV keys or a
   `user_id` column to `GameEvent` without revisiting the signup guard and writing a full
   per-user migration — a partial change creates split-brain projections.
4. **Login still works** when signup is closed — do not touch `/token/`.

## Tests to add (`server/tests/test_auth.py`)
Use the existing `client` fixture (TestClient + per-test in-memory DB). **Every test here that needs
the guard active must `monkeypatch.setattr(settings, "single_user", True)` first** — the suite
default is `single_user=False` (see "Test impact") so the rest of the corpus keeps working.
- `test_first_signup_succeeds`: POST `/signup/` with a strong password → 200/201, returns a token
  (works with the guard on or off).
- `test_second_signup_blocked`: with `single_user=True`, sign up user A, then POST `/signup/` for
  user B → **409** with the "single-user" detail; assert the DB still has exactly one user.
- `test_second_signup_does_not_hash_password`: with `single_user=True`, monkeypatch
  `AuthService.get_password_hash` to raise if called; second signup must 409 **without** invoking the
  hash (guard runs first).
- `test_login_works_after_registration_closed`: with `single_user=True`, after the guard would trip,
  user A can still POST `/token/` and authenticate.
- `test_allow_signup_false_returns_403`: set `settings.allow_signup=False` (monkeypatch) → first
  signup itself returns 403 (independent of `single_user`).
- `test_multi_user_signup_allowed_when_single_user_off`: with `single_user=False` (the suite
  default), two distinct `/signup/` calls both succeed — pins that the cross-user corpus is
  unaffected.

## User-centric & edge-case checks
- The 409 message is human-readable and explains *why* (not a bare "conflict"), so a confused
  second user understands registration is closed rather than thinking the server is broken.
- Distinct from the existing username/email 409s — a generic-enough message that we do **not** leak
  whether a specific username exists (the report flagged enumeration via distinct 409 messages;
  here the single-user 409 fires before username/email lookup, so it can't be used to probe).
- Guard tolerates a pre-seeded user (count ≥ 1), not just users created via signup.

## Test impact — the single-user guard collides with the cross-user test corpus (read first)
The guard `existing >= 1 → 409` blocks **every** second `/signup/`. That is not a handful of stray
tests — it is the entire **cross-user isolation / IDOR** corpus, which deliberately signs up *two*
users in one test to prove user A can't touch user B's data. Verified callers that sign up two users
in a single test:
- `test_completion_audit.py:63-64, 92-93, 119-120, 148-149` (alice + bob — the IDOR /
  cross-user-rejection tests)
- `test_mcp_keys_api.py:179-190` (userA/B/C/D)
- `test_v2_features.py:83-86` (and similar)

These tests are the security boundary. **Do NOT "convert them to direct DB inserts and move on"** —
inserting the second user via `db_session` deletes the very thing several of them assert (that the
signup → token → authed-request path enforces ownership end-to-end). Instead:

1. **Default the suite to multi-user-allowed.** In `conftest.py`, force `settings.single_user=False`
   for the suite (a session-autouse fixture or the env default), so by default every existing
   multi-user test keeps creating both users via the real `/signup/` → auth path **unchanged**. The
   guard is gated on `single_user` exactly to allow this.
2. **Test the guard explicitly with it ON.** The new Step-01 tests (`test_second_signup_blocked`,
   etc.) opt **in** via `monkeypatch.setattr(settings, "single_user", True)` for just that test —
   mirroring how the MCP 429 test enables `mcp_rate_limit_enabled` for itself only.
   - Note this is **not** the slowapi gotcha from Step 02: `single_user` is read fresh from the
     `settings` singleton inside the request handler (`auth.py::signup`), so `monkeypatch.setattr`
     **does** reach it. Only the slowapi limiter has the frozen-at-construction problem.
3. Keep at least one end-to-end cross-user IDOR test running with `single_user=False` so the
   ownership boundary stays covered by a real two-user signup flow (don't let every such test get
   silently downgraded to a single-user variant).

## Regression guardrails
- Run the **whole** auth suite: `pytest -q server/tests/test_auth.py` — existing tests that create
  one user must still pass (they create the first user, which is allowed).
- Run the **whole** suite after adding the `single_user=False` default fixture and reconcile any
  multi-user test that was creating two users via `/signup/` — they must stay green via the
  suite-default-off fixture (item 1 above), **not** by rewriting them. Per-test opt-in (item 2) is
  only for the guard's own tests.

## Done-when
- [ ] `single_user` / `allow_signup` settings exist and documented.
- [ ] With `single_user=True`, second `/signup/` returns 409 before any password hashing; first still
      works.
- [ ] Suite defaults to `single_user=False`; the cross-user IDOR corpus
      (`test_completion_audit.py`, `test_mcp_keys_api.py`, `test_v2_features.py`) stays green
      **unmodified** (no conversion to direct DB inserts), and at least one end-to-end two-user IDOR
      test still runs.
- [ ] `game/__init__.py` documents why global keys are intentional + the "don't half-fix" warning.
- [ ] New auth tests green; full `test_auth.py` and the full suite green.
