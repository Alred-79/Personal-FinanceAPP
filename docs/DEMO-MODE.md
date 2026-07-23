# Demo Mode — Runbook

A gated "demo mode" lets anyone log into a pre-seeded, data-rich showcase
account with one tap (or by typing `demo` / `Demo123!`) — **without weakening
security anywhere else**. This is the operator's guide. The design rationale and
the security assessment live in [`DEMO-MODE-PLAN.md`](./DEMO-MODE-PLAN.md).

## What it is (and isn't)

- **Not** a password backdoor. `POST /api/demo-login/` is **parameterless** — it
  takes no username/password input and only ever loads the single hardcoded
  `demo` user, through the **same hardened auth machinery** as `/token/`
  (httpOnly cookies, refresh rotation + family revocation, per-IP rate limit).
- Gated by `DEMO_MODE_ENABLED` (default **off**). When off, `demo-login` and the
  "Enter the demo" button **do not exist** (404 / hidden).
- The `demo` user is an ordinary `disabled=0` user. Every request still flows
  `auth → get_current_active_user → RLS`, so a demo session can only ever see the
  demo user's rows — never a real account's data.
- Enabling the flag alone is not readiness. `GET /api/demo-status/` checks the
  exact Alembic head and the canonical seed contract. Login returns 503 and sets
  no cookies until both are ready; request paths never migrate or seed.

## Credentials

| username | password |
| --- | --- |
| `demo` | `Demo123!` |

Configurable in the `DEMO` dict in `server/scripts/seed_demo.py`. The password
meets the strength rule (8+ chars, upper/lower/digit/special).

## Deploy as a SEPARATE instance — never on the real account's instance

The showcase feature flags are **global, not per-user**, and the public LLM
surface is a denial-of-wallet / prompt-injection risk. Both are eliminated by
running the demo as its own Railway service with its **own Postgres**. Do **not**
turn `DEMO_MODE_ENABLED=true` on the instance that serves your real account.

### `persfin-demo` `.env`

```env
# gate + isolation
DEMO_MODE_ENABLED=true
ENVIRONMENT=production            # real cookie 'secure', strict validators
SINGLE_USER=true                  # only the demo user exists
ALLOW_SIGNUP=false                # no demo2 accounts (keeps per-user LLM cap = instance cap)
MCP_ENABLED=false
SCHEDULER_ENABLED=false           # no background work in the public showcase
COOKIE_DOMAIN=<exact demo hostname>
ALLOWED_ORIGINS=["https://<exact demo hostname>"]

# hard LLM caps (orders of magnitude below prod) — bounds denial-of-wallet
LLM_DAILY_REQUEST_BUDGET=10
LLM_DAILY_COST_BUDGET_CENTS=5

# showcase feature bundle (global flags — safe here: this DB has only the demo user)
TAX_FEATURES_ENABLED=true
FREELANCER_MODE_ENABLED=true
MERCHANT_LIFECYCLE_ENABLED=true
AUDITOR_ENABLED=true
SUBSCRIPTION_ACTIONS_ENABLED=true
BEHAVIORAL_EARMARKS_ENABLED=true
```

## Deterministic bootstrap

The canonical persona is Maya Chen, a salaried renter with side income. Game
mode stays off; the seed creates no MCP credentials/audit activity and invents
no forecast-calibration history. Rule executions come from the real RuleEngine
over seeded transactions. Lifecycle amounts/dates and price changes are derived
from the ledger (the lifecycle probability remains explicitly modeled output).

The container runs migrations first, then `seed_demo --bootstrap` when demo mode
is enabled. An absent demo user is seeded, a ready canonical seed is a no-op, and
an incomplete existing demo causes deployment to fail without mutation.

### Local (SQLite)

```bash
cd Personal-FinanceAPP
rm -f .demo/showcase.db                        # dedicated demo DB only
export DATABASE_URL=sqlite:///.demo/showcase.db
./.venv/bin/alembic upgrade head
DEMO_MODE_ENABLED=true ./.venv/bin/python -m server.scripts.seed_demo --bootstrap
```

### Railway (dedicated demo Postgres)

```bash
# point DATABASE_URL at the demo Postgres (postgresql+psycopg://...)
alembic upgrade head
python -m server.scripts.seed_demo --bootstrap
```

## Reset

Prefer dropping/re-provisioning the dedicated demo database and redeploying. An
operator can intentionally replace only the demo user's financial showcase rows
with `python -m server.scripts.seed_demo --reset-financials`. The explicit flag
exists because this is destructive. Never point it at the production service.

## Security guards (already in code)

- **Bank linking blocked** on the demo account — `routers/plaid.py` `link-token`
  and `exchange-public-token` 403 for `demo` (`is_demo_user`). Stops a visitor
  attaching a REAL Plaid item to the shared account.
- **Self-immutable** — `routers/users.py` `change-password` 403s for `demo`, so a
  visitor can't change the password + `revoke_all_user_tokens` and kick everyone.
- **Canonical ledger is read-only** — the authenticated router dependency
  rejects demo financial commands with `403 / demo_read_only`, before route
  code runs. Dry-run rule previews and scenario compose/compare/evaluate calls
  remain available because they do not persist changes. Ordinary users and
  deployments with demo mode off are unaffected.
- **Parameterless login** — nothing to enumerate or credential-stuff.
- **Rate-limited** (per-IP `login_rate_limit`) + the demo user's refresh tokens
  are pruned/capped so repeated taps can't bloat the table.
- **`SameSite=Strict`** cookies on the demo-login path.
- **Shared-session isolation** — one demo visitor's stale refresh token is
  rejected without revoking unrelated demo visitors. Ordinary accounts retain
  whole-family revocation on refresh-token reuse.

## Turning it off

Set `DEMO_MODE_ENABLED=false` (or unset) and redeploy. `demo-login` 404s and the
"Enter the demo" button disappears — the entry point is gone. The seeded `demo`
user can be deleted (FK cascade) to remove its financial data; the append-only
game stream only goes away by dropping the database.

## Verification

See [`DEMO-MODE-PLAN.md` §9](./DEMO-MODE-PLAN.md). Unit/security coverage lives in
`server/tests/test_demo_mode.py` (`./.venv/bin/pytest -q server/tests/test_demo_mode.py`).
