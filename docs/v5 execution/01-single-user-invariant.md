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
3. **Document the invariant** at the top of `server/src/services/game/__init__.py` (module
   docstring): game projections (XP/streak/grace/boss/homestead/CategorySettings) are deliberately
   global keys because the instance is single-user (Step 01); do **not** add per-user KV keys or a
   `user_id` column to `GameEvent` without revisiting the signup guard and writing a full
   per-user migration — a partial change creates split-brain projections.
4. **Login still works** when signup is closed — do not touch `/token/`.

## Tests to add (`server/tests/test_auth.py`)
Use the existing `client` fixture (TestClient + per-test in-memory DB).
- `test_first_signup_succeeds`: POST `/signup/` with a strong password → 200/201, returns a token.
- `test_second_signup_blocked`: sign up user A, then POST `/signup/` for user B → **409** with the
  "single-user" detail; assert the DB still has exactly one user.
- `test_second_signup_does_not_hash_password`: monkeypatch `AuthService.get_password_hash` to raise
  if called; second signup must 409 **without** invoking the hash (guard runs first).
- `test_login_works_after_registration_closed`: after the guard would trip, user A can still POST
  `/token/` and authenticate.
- `test_allow_signup_false_returns_403`: set `settings.allow_signup=False` (monkeypatch) → first
  signup itself returns 403.

## User-centric & edge-case checks
- The 409 message is human-readable and explains *why* (not a bare "conflict"), so a confused
  second user understands registration is closed rather than thinking the server is broken.
- Distinct from the existing username/email 409s — a generic-enough message that we do **not** leak
  whether a specific username exists (the report flagged enumeration via distinct 409 messages;
  here the single-user 409 fires before username/email lookup, so it can't be used to probe).
- Guard tolerates a pre-seeded user (count ≥ 1), not just users created via signup.

## Regression guardrails
- Run the **whole** auth suite: `pytest -q server/tests/test_auth.py` — existing tests that create
  one user must still pass (they create the first user, which is allowed).
- Grep the test suite for any test that creates **two** users via `/signup/`; convert those to the
  `db_session` fixture (insert the second user directly) so they don't trip the new guard. If none
  exist, note that in the step's completion.

## Done-when
- [ ] `single_user` / `allow_signup` settings exist and documented.
- [ ] Second `/signup/` returns 409 before any password hashing; first still works.
- [ ] `game/__init__.py` documents why global keys are intentional + the "don't half-fix" warning.
- [ ] New auth tests green; full `test_auth.py` green.
