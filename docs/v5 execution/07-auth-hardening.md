# Step 07 — Auth hardening

## Goal
Finish the httpOnly-cookie migration (stop echoing the refresh token in JSON bodies), make the
password-change flow safe (strength check + session revocation), and surface `game_mode` from
`/users/me/`.

## Why it matters (user impact)
- The app deliberately stores refresh tokens as httpOnly cookies so JavaScript — and therefore an
  XSS payload — can't read them. **Echoing the same refresh token in the JSON response body throws
  that away**: any XSS that can read a fetch response can mint sessions. The user gets none of the
  protection the cookie design promised.
- A user changing their password almost always intends "lock everyone else out" (e.g. after a
  shared device, or suspicion of compromise). Today the change neither enforces password strength
  *nor* revokes other sessions — so a stolen session survives the very action meant to kill it, and
  a weak new password is accepted.
- `/users/me/` always reporting `game_mode="off"` means the UI can't trust the server for the
  user's actual mode — a small correctness bug that makes game features flicker/reset.

## Findings closed (with evidence)
- **Refresh token in JSON body:** `routers/auth.py:59-63` (login), `:88-92` (signup), `:119-123`
  (refresh) all return `Token(..., refresh_token=...)` while *also* setting the httpOnly cookie.
- **Password change unsafe:** `routers/users.py:38-53` verifies the current password then sets the
  new hash directly — no `validate_password_strength`, no `revoke_all_user_tokens`. (Strength
  validation *does* exist and is used at signup: `auth_service.py:122-123`.)
- **`game_mode` dropped:** `auth_service._to_user_in_db` (`:51-62`) never copies `game_mode`; the
  `UserInDB` default is `"off"`, so `/users/me/` is always "off".

## Preconditions
- Confirm the client reads auth from cookies, not the JSON body. **Grep `client/src` for
  `refresh_token`** first; if the client uses the body field anywhere, migrate it to rely on the
  cookie (the access token can stay in the body if the SPA needs it for the Authorization header).
- `revoke_all_user_tokens` (or equivalent) exists in `auth_service` — confirm the exact name.

## Implementation
1. **Drop the refresh secret from response bodies** (`routers/auth.py`): in login, signup, and
   refresh, return a `Token` **without** `refresh_token` (keep `access_token` + `token_type` if the
   SPA needs the access token; otherwise return a minimal body). The refresh cookie is still set via
   `set_auth_cookies`. Update the `Token` model / its usages so the field is optional or removed,
   and update any client/types that referenced it.
2. **Harden password change** (`routers/users.py::change_password`):
   - Call `AuthService.validate_password_strength(new_password)` before hashing (raises 422 on weak).
   - After updating the hash, call `auth_service.revoke_all_user_tokens(db, user)` to kill existing
     refresh-token families, **then** issue a fresh cookie pair for the current session so the user
     who just changed their password isn't logged out of the tab they're in. (Verify the revoke
     helper's signature; if it takes a user id, pass `user_row.id`.)
   - Reject reusing the same password (optional, nice-to-have) — at least don't *require* it.
3. **Copy `game_mode`** in `auth_service._to_user_in_db`: add
   `game_mode=cast(str, getattr(user, "game_mode", "off"))` so `/users/me/` reflects the row.
   (Also check `read_queries.py:296-305`'s loader — if it omits `game_mode` too, fix it there for
   consistency.)

## Tests to add (`server/tests/test_auth.py`, `test_v2_features.py` / wherever `/users/me/` is)
- `test_login_body_has_no_refresh_token`: login response JSON has no `refresh_token` key, but the
  `Set-Cookie` for the refresh cookie is present.
- `test_signup_body_has_no_refresh_token` and `test_refresh_body_has_no_refresh_token`: same for
  the other two endpoints; the rotated refresh cookie is still set on `/refresh/`.
- `test_password_change_rejects_weak`: change to `"weak"` → 422; the old password still works.
- `test_password_change_revokes_other_sessions`: log in twice (two refresh tokens); change the
  password via session A; session B's `/refresh/` now fails (revoked), while session A still works.
- `test_password_change_requires_correct_current`: wrong current password → 401/403, no change.
- `test_users_me_reports_game_mode`: set the ORM `game_mode` to a non-"off" value; `/users/me/`
  returns it.

## User-centric & edge-case checks
- After a password change the **current** tab stays logged in (fresh cookie issued) — the user
  isn't bounced to login by their own action — while every *other* device is logged out.
- The weak-password 422 message lists the exact rules (length, char classes) so the user can fix it
  in one try (reuse `validate_password_strength`'s message).
- Refresh still works purely from the cookie after the body change — verify the refresh endpoint
  reads `request.cookies.get(REFRESH_COOKIE)` (it does, `auth.py:103`) and never the body.
- `cookie_domain` set vs unset: logout/clear behaves (note the report's "logout doesn't clear
  cookies when cookie_domain is set" — if in scope, set the same domain on the clear; otherwise log
  it for the backlog).

## Regression guardrails
- Don't break Swagger `/docs` Bearer flow (access token still available where the SPA/docs expect).
- Grep client for `refresh_token` usage and migrate before removing the field, so the SPA login
  flow keeps working.
- Run `pytest -q server/tests/test_auth.py` and any `/users/me/` test.

## Done-when
- [ ] No refresh token in any JSON body; refresh cookie still set/rotated.
- [ ] Password change enforces strength and revokes other sessions while keeping the current one.
- [ ] `/users/me/` reports the real `game_mode`.
- [ ] Client still authenticates end-to-end; auth tests green.