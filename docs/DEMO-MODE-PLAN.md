# Demo Mode — Design, Security Assessment & Implementation Plan

> **Status: PLAN ONLY — not yet implemented.** This document specifies a gated
> "demo mode" (a fake username/password that logs into a pre-seeded, data-rich
> account) and the security hardening required before it can be exposed publicly.
> It is the output of a multi-pass adversarial security review; build it as
> specified, with every guard in §5, before any public deploy.

---

## 1. Goal

Provide a **fake username + password that logs straight into an authenticated
session pre-filled with plentiful mock data** showcasing every feature of the app
at its finest — **without weakening security anywhere else.**

**Credentials:** username `demo` / password `Demo123!` (meets the strength rule:
8+ chars, upper/lower/digit/special). Configurable in the seed's `DEMO` dict.

These work via the normal login form; a one-tap **"Enter the demo"** button uses
a dedicated flag-gated endpoint so the password is never shipped to the browser.

---

## 2. Core design — why this does not weaken security

This is **not** a password backdoor. It is a **real seeded user** that logs in
through the **normal, already-hardened auth machinery**, gated by an env flag that
is **off by default** so the feature does not exist in any environment that hasn't
opted in.

- New flag `demo_mode_enabled: bool = False` in `server/src/settings.py` (env
  `DEMO_MODE_ENABLED`). Default off ⇒ production-safe by default.
- `POST /api/demo-login/` **404s when the flag is off**; when on it **only ever
  logs in the single hardcoded `demo` username** (no username input). It cannot
  authenticate any other account and does **not** touch the real `/token/` path.
- It reuses the existing helpers verbatim — `create_access_token`,
  `create_refresh_token`, `set_auth_cookies` — so cookie flags, refresh rotation,
  and rate limiting are identical to normal login.
- The demo user is an ordinary `disabled=0` user. Every request still flows
  `auth → get_current_active_user → get_tenant_db/set_tenant → RLS`, so the demo
  session can only ever see the demo user's rows. It cannot read the real
  account's data.
- `auth_router` is registered **without** the tenant dependency
  (`server/src/main.py:200`), so the public `demo-login` / `demo-status` routes
  belong there cleanly.

---

## 3. Security assessment (verdict)

Produced by a layered review: three parallel audits (threat-model + reversibility,
auth/session/RLS/secrets, injection/LLM-firewall/MCP/uploads) plus a fourth
independent adversarial pass against this plan.

### 3.1 Will it cause security damage? — The demo-login itself: **No.**

It is password-less but **non-parameterized** (hardcoded to `get_user(db,"demo")`)
— no username input ⇒ no enumeration, no credential stuffing, no way to
authenticate any other account. It rides the *independently-verified* hardened
model:

- JWT forgery rejected + algorithm-pinned (`alg=none`/wrong-secret/expired → 401).
- Refresh-token rotation **with family revocation** (RFC 6819 §5.2.2.3).
- **Systematic IDOR isolation** — ~107 endpoints scope to `current_user.id`;
  cross-user read → 404.
- **Complete, fail-closed RLS** — 37 tenant tables; credential tables correctly
  excluded; no GUC ⇒ no rows.
- The assistant can only **propose**; every write requires a **single-use,
  replay-proof confirm token** (`UNIQUE(jti)` claimed in the write txn).

A stranger in the demo session can only touch demo-scoped data and **cannot move
real money**. Cookies are httpOnly / SameSite=Lax / secure-in-prod.

### 3.2 The real risks (operational) — removed by a separate demo instance

1. **Flag-bundle blast radius (the footgun).** The showcase flags
   (`tax/auditor/merchant_lifecycle/subscription_actions/freelancer/behavioral_*`)
   are **global, not per-user**. Enabling them on the instance that serves the
   **real** account silently activates nightly jobs, LLM/PyMC cost, and
   notifications for the real account too. (All propose/notify-only — cost/privacy
   churn, not a breach.)
2. **Public shared LLM surface.** A public one-tap demo lets anyone drive the
   assistant / receipt-scan ⇒ (a) **denial-of-wallet** (the streaming token budget
   is advisory-only; the hard cap is requests/day), and (b) **prompt-injection on
   the main chat is still partially open** (OWASP LLM01; blast radius is "what the
   assistant says," not writes, thanks to propose→confirm).

**Both are eliminated by deploying the demo as a SEPARATE Railway service with its
OWN Postgres** (see §6) — never on the real account's instance.

### 3.3 Is it reversible?

| Change | Undo | Clean? |
| --- | --- | --- |
| Code (flag, two endpoints, guards, frontend button) | `git revert` / flag off | ✅ Yes — no schema/migration |
| Flag bundle | set `false` + redeploy | ⚠️ Mostly — already-emitted notifications / lifecycle fits persist |
| Seed financial data | delete demo user (FK cascade) | ✅ Yes |
| Seed **game** data (`game_events`, `runs.map_json`) | **append-only via DB triggers** | ❌ **No** — cannot delete without dropping the DB |

⇒ Fully reversible **only on a dedicated demo database you can drop.** This is the
deciding reason for a separate instance.

### 3.4 Pre-existing items (NOT caused by this plan; for awareness)

- Prompt-injection hardening on main chat (P0, write-gated).
- Advisory-only streaming LLM token budget (P1).
- `jwt_algorithm` not pinned to a whitelist (low / defense-in-depth).
- MCP vault single-worker invariant (ships dark; not a leak).
- Plaid manual-edit overwrite (UX/data).
- Local `.env` holds real keys but is **gitignored and never committed** (verified
  via `git log --all` + `git ls-files`). Confirm the GitHub repo is **private**;
  rotate keys only if the machine/repo was ever exposed.

---

## 4. Decisions

- **Game layer:** full event-sourced (built via the engine's real machinery, §7).
- **Feature flags:** all showcase flags ON — but **only on the demo instance**.
- **Deployment:** a **separate** `persfin-demo` Railway service + its own Postgres
  (safe + fully tear-down reversible).
- **AI surface:** the assistant + receipt/doc scan stay **live behind a hard, low
  LLM budget cap** (fuller showcase; injection there is write-gated).

---

## 5. Required hardening (before any public deploy)

A stranger shares the single `demo` account, so the demo user must be protected
from itself and from poisoning other visitors. New code guards mirror the existing
`_require_enabled` pattern in `server/src/routers/tax.py`.

- **[CRITICAL] Block real-bank linking on the demo account.** 403 guard
  (`is_demo_user(current_user)`) at the top of `routers/plaid.py` `link-token` and
  `exchange-public-token`. Otherwise a visitor could attach a REAL Plaid item to
  the demo user and exfiltrate real bank data.
- **[CRITICAL] Make the demo account self-immutable.** 403 guard on
  `routers/users.py` `change-password` (and any profile/email mutation) when the
  user is `demo` — otherwise a visitor changes the password +
  `revoke_all_user_tokens`, locking and kicking every other visitor.
- **Demo-login is parameterless.** No form/body input — flag check, then the fixed
  `get_user(db,"demo")`. Nothing to enumerate or stuff.
- **Flag gate as a `Depends` guard** (`_require_demo_enabled` → 404), evaluated
  before the handler, on both demo routes.
- **Refresh-token farming guard.** Inherit per-IP `settings.login_rate_limit`
  (limiter is per-IP; `trust_proxy=False`), AND prune/cap the demo user's active
  `refresh_tokens` (keep newest N) so repeated taps can't bloat the table.
- **Tighter cookies on the demo-login path** — add an optional `samesite` param to
  `set_auth_cookies`; pass `"strict"` for demo-login.
- **Vision/LLM paths** — confirm receipt-scan + import (`routers/receipts.py`,
  `routers/imports.py`) run the same `services/pii.scrub_secrets` + advice firewall
  as chat before model output is used; document the indirect-injection surface
  (receipt/PDF text).

**Shared-account property (accept + mitigate):** one shared `demo` account means
visitors see/edit the same goals/budgets/scenarios and can poison each other's
view. Acceptable IF the dangerous mutations above are blocked and the demo DB is
**periodically re-seeded** (cron/redeploy). *Future option (out of scope): an
ephemeral per-visitor cloned demo account.*

---

## 6. Demo-instance configuration (HARD requirements)

The `persfin-demo` Railway service runs its **own** Postgres and **own** `.env`,
distinct from the real instance:

```env
# gate + isolation
DEMO_MODE_ENABLED=true
ENVIRONMENT=production            # real cookie 'secure', strict validators
SINGLE_USER=true                  # only the demo user exists
ALLOW_SIGNUP=false                # no demo2 accounts (keeps the per-user LLM cap = instance cap)
MCP_ENABLED=false
SCHEDULER_ENABLED=false           # don't burn LLM budget on nightly jobs; seed the auditor/lifecycle
                                  #   outputs directly so they still render. (If ever on: single worker / scheduler_leader.)
COOKIE_DOMAIN=<exact demo hostname>
ALLOWED_ORIGINS=["https://<exact demo hostname>"]

# hard LLM caps (orders of magnitude below prod) — bounds denial-of-wallet
LLM_DAILY_REQUEST_BUDGET=10
LLM_DAILY_COST_BUDGET_CENTS=5

# showcase feature bundle (global flags — safe here because this DB has only the demo user)
TAX_FEATURES_ENABLED=true
FREELANCER_MODE_ENABLED=true
MERCHANT_LIFECYCLE_ENABLED=true
AUDITOR_ENABLED=true
SUBSCRIPTION_ACTIONS_ENABLED=true
BEHAVIORAL_EARMARKS_ENABLED=true   # + other behavioral_* as desired
```

**Reset** = drop & re-provision the demo Postgres, then re-seed (the append-only
game tables make in-place wipe impossible).

---

## 7. Implementation

### 7.1 Part A — Gated demo-login mechanism

**Backend** (`settings.py`, `routers/auth.py`):
1. Add `demo_mode_enabled: bool = False` near the other feature flags.
2. `GET /api/demo-status/` (public) → `{ "enabled": settings.demo_mode_enabled }`
   so the logged-out UI can show/hide the button. Leaks nothing.
3. `POST /api/demo-login/` (public, parameterless, `Depends(_require_demo_enabled)`,
   per-IP rate-limited, `samesite="strict"`):
   - Load `demo` via `auth_service.get_user(db, "demo")`; 503 "run the seed" if
     missing; 403 if `disabled`.
   - Issue access+refresh cookies via the existing helpers; return a `Token`.

**Frontend** (`client/src/pages/Login/Login.tsx`, optionally a landing CTA):
- On mount, `GET /demo-status/`; if `enabled`, render an "Enter the demo" button
  (engraved-ledger styled).
- Click → `POST /demo-login/` → `useStore.setState({ isLoggedIn: true })` →
  `navigate("/")`. Graceful toast on failure. Surface the typed credentials nearby.

### 7.2 Part B — Plentiful showcase seed (financial domains)

Extend `server/scripts/seed_demo.py` into the canonical showcase seed (keep the
`demo` creds). Factor into per-domain helpers and **expand `reset_user()` to wipe
every table the seed owns** (by `user_id`). Use `CANONICAL_CATEGORIES`
(`services/categorization_service.py`), integer cents, ISO dates, deterministic RNG.

- **User config:** `game_mode='full'`, `savings_percent=15`, `s2s_include_income=1`,
  `s2s_include_goals=1`, `s2s_buffer=5000`, `birth_year`, `spend_warning=20`.
- **Accounts (3):** checking ~$3.4k, HYSA ~$11k, credit ~-$840.
- **Income (~12 mo):** bi-weekly W-2 (`source_type='w2'`, `recurrence='bi-weekly'`)
  + **lumpy self-employment** (`source_type='self_employment'`, CoV > 0.8) so the
  income-volatility buffer recommends a real number; a couple of `other` rows.
- **Expenses (~150 over 4–6 mo):** monthly recurring bills (`recurrence='monthly'`)
  + dense discretionary across ≥8 categories + **a deliberate spending
  regime-shift** (~+$465/mo partway) so the forecast change-point detector fires;
  a few subscription merchants with ≥3 historical charges (one price hike, one
  dormant 90+ days).
- **Budgets (~8):** mixed over/under/on-pace, `rollover=1` on 2–3.
- **Goals (5–6):** 0% / 20% / 70% / 97% / completed, varied deadlines; **earmarks**
  partitioning the Emergency Fund (sum ≤ progress).
- **BalanceSnapshots:** one/day over the window, gentle uptrend.
- **Liabilities (2–3):** credit card (`is_active_boss=1`), car/student loan, varied
  APR; a `LiabilityAdjustment` or two.
- **Subscriptions / MerchantLifecycle:** `probability_alive` / `status` / `cadence`
  / `price_change_pct` spanning active / lapsing / dormant.
- **Tax:** `TaxTag`s across Schedule-C buckets (validate via `services/tax/buckets.py`)
  on office/vehicle/meals(50%)/travel; `TaxDocument`s (W-2 confirmed, 1099-NEC
  pending, 1098); `MileageLog` (5–6 trips); `MerchantTaxBucket` mappings.
- **Scenarios (2):** valid `overlay_json` via `services/scenario_overlay.py`
  ("Freelance full-time", "Emergency-fund boost"); one committed `PlanOfRecord`.
- **Rules (3)** + `RuleExecution`s; **MerchantCategory** + **UserMemory** facts +
  **CategorySettings**; **Notifications (5–8)** mixed read/unread with stable `ref`.

### 7.3 Part C — Full event-sourced game layer (the proper way)

The engine's hard rule (`services/game/backfill.py`): **never fabricate a fake
event stream from rows.** Build an "established player" by driving the **real
machinery** after the finances are seeded:

1. `services/game/backfill.run_backfill(session)` — baseline snapshot (idempotent).
2. Walk the historical window and invoke the engine's own ticks so events arise
   legitimately and fold into projections via `services/game/events.record_events`:
   - Weekly: `services/game/metrics.run_weekly_rollups(db, as_of)` for each past
     week (GREEN_WEEK / rollups).
   - Monthly close: the pure entry point used by `_monthly_tick` (`scheduler.py`)
     for each past month → seals a `Run` (Expedition); leaves the current month
     in-progress.
   - Streak/daily activity across recent days (`services/game/daily.py`) so
     `streak_view` shows a real current+best streak.
   - Boss/campaign/challenge progression emitted by those services as ticks run.
3. Projections fold synchronously inside `record_events`; confirm `ProjectionMeta`
   watermarks are caught up (rebuild path if needed).

Result: Keeper stats (vitality/mana/armor/might compute live from the seeded
finances), real XP/level + streak, Expedition months, campaigns/challenges — all
consistent with the projection/append-only invariants.

### 7.4 Reset / idempotency caveat

`game_events` and `runs.map_json` are **append-only (DB triggers block
UPDATE/DELETE)** — `reset_user()` wipes its financial tables but cannot delete game
events, and re-running stacks a second history. Therefore:

- **For a clean re-seed, run on a FRESH database.** Local: remove
  `finance_tracker.db` → `alembic upgrade head` → seed. Railway: a dedicated demo
  Postgres, never the personal DB.
- Provide a `--fresh` guard in the seed that refuses the game-layer portion if a
  demo `game_events` stream already exists; the financial portion stays idempotent
  via `reset_user`.

---

## 8. Files to create / modify

| File | Change |
| --- | --- |
| `server/src/settings.py` | add `demo_mode_enabled` flag |
| `server/src/routers/auth.py` | `demo-status` + `demo-login` (parameterless, `Depends(_require_demo_enabled)`, per-IP rate limit, `samesite="strict"`) |
| `server/src/routers/plaid.py` | 403 demo-guard on `link-token` + `exchange-public-token` |
| `server/src/routers/users.py` | 403 demo-guard on `change-password` (+ profile/email) |
| `server/src/services/auth_service.py` | `is_demo_user()` helper; optional `samesite` on `set_auth_cookies`; demo refresh-token prune/cap |
| `server/scripts/seed_demo.py` | expand into the full showcase seed (per-domain helpers, broadened `reset_user`, game backfill+ticks, `--fresh` guard) |
| `client/src/pages/Login/Login.tsx` (+ maybe a landing CTA) | demo-status fetch + "Enter the demo" button |
| `docs/DEMO-MODE.md` | runbook: credentials, env bundle, seed command, reset/fresh-DB, security model |
| `server/tests/` | new demo-mode security tests (see §9) |

**Reuse (don't re-implement):** `services/auth_service.py` helpers; the
`_require_enabled` guard pattern in `routers/tax.py`; seed scaffolding (`cents()`,
RNG, date cursors); game machinery (`backfill.run_backfill`,
`events.record_events` + `GameEventDraft`, `metrics.run_weekly_rollups`, the
monthly-close entry point, `daily.streak_view`); overlay/bucket validators; the
frontend post-login flow in `Login.tsx` + `store.fetchUser`.

---

## 9. Verification

1. **Security/unit** (`./.venv/bin/pytest -q`) — prove: `demo-login` 404s when the
   flag is off and only ever authenticates `demo` when on; a demo session **cannot
   change the demo password/email** (403) and **cannot link Plaid** (403); cannot
   read another user's rows; per-IP rate limit holds; all existing auth/RLS tests
   stay green.
2. **Seed on a fresh DB** — remove `finance_tracker.db` → `alembic upgrade head` →
   `DEMO_MODE_ENABLED=true … python -m server.scripts.seed_demo` (with the bundle);
   confirm sensible counts and no integrity errors.
3. **End-to-end (chrome-devtools MCP)** — start backend (uvicorn) + frontend (vite
   :5173); on `/login` click "Enter the demo" (and separately type
   `demo`/`Demo123!`); walk **every page** — Overview (S2S band + breakdown),
   Forecast (trough band + regime-shift + scenarios), Almanac (heat-grid +
   net-worth + Flow Sankey), Budgets, Goals/Reliquary (earmarks), Subscriptions
   (active/lapsing/dormant + price creep), Tax, Income (volatility + buffer),
   Debts/Expedition/Keeper, Notifications — screenshot each.
4. **Flag-off check** — unset `DEMO_MODE_ENABLED`; confirm `demo-login` 404s and the
   button hides (the backdoor is gone).
5. Confirm the demo runs as a separate Railway service + dedicated Postgres, seeded
   once on a fresh DB, with the §6 env block applied.
