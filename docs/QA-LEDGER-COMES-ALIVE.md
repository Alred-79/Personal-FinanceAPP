# Live QA — "The Ledger Comes Alive"

Hands-on test plan for the frontend wave on branch **`feat/ledger-comes-alive`**
(eight surfaces that newly expose under-used backend capability). This is the one
verification automated tests can't do: the live render, the 3D, motion, and the
mode × theme × reduced-motion matrix.

**Automated gates already green** (re-run any to confirm): `npx tsc -b` · frontend
`npm run test -- --run` (234) · backend `./.venv/bin/python -m pytest -q` (1447) ·
`npm run build` (the `Reliquary-*.js` three/R3F chunk is separate from the main
bundle) · `./.venv/bin/python -m alembic heads` (single head `a7e920260619`).

---

## 0. Prerequisites

- On the branch: `git -C "Personal-FinanceAPP" checkout feat/ledger-comes-alive`
- Deps already installed (`three`/`@react-three/fiber@8`/`@react-three/drei@9` were
  added this wave). If a clean machine: `npm install` and `./.venv/bin/pip install -e .`
  (or your usual venv sync).
- `.env` exists and has `JWT_SECRET_KEY` (required to boot). `GROQ_API_KEY` is only
  needed for the assistant / receipt-scan / tax-doc-extract — **not** for any surface
  in this wave.
- Chrome (for the 3D + DevTools perf checks).

---

## 1. Run the app

Two terminals, from `Personal-FinanceAPP/`:

```bash
# Terminal A — backend (FastAPI on :8000). Run migrations first.
./.venv/bin/python -m alembic upgrade head
./.venv/bin/uvicorn server.src.main:app --reload --port 8000

# Terminal B — frontend (Vite on :5173)
npm run dev
```

Open **http://localhost:5173**. In dev the client talks to `http://localhost:8000/api`
directly (no proxy; CORS allows `:5173`). If the API port differs, the client won't
reach it — keep the backend on **8000**.

> The migration step also creates the new **`mcp_audit_log`** table. Confirm it ran:
> `./.venv/bin/python -m alembic current` should show `a7e920260619 (head)`.

---

## 2. Seed data + flags

### 2a. Demo data

```bash
./.venv/bin/python -m server.scripts.seed_demo
```

Creates the **`demo` / `Demo123!`** user with a checking account, ~4 months of
categorized transactions, monthly recurring bills, a paycheck, and **3 goals**
(one near-complete, one early, one fully met). Idempotent — safe to re-run. Log in
as `demo` / `Demo123!`.

### 2b. Feature flags (edit `.env`, then **restart the backend**)

The wave's gated surfaces are dark by default. Turn them on for QA:

```ini
# .env  (UPPER_SNAKE; the client reads these via GET /settings/)
MCP_ENABLED=true                  # → Agent Vault (Settings → Agent Keys)
FREELANCER_MODE_ENABLED=true      # → the Income nav + /income surface
MERCHANT_LIFECYCLE_ENABLED=true   # → subscription vitality / probability fields
TAX_FEATURES_ENABLED=true         # → the Tax Organizer nav + page
```

> Flags are read at process start — **restart uvicorn** after editing `.env`. The
> nav entries (Income, Tax) appear after a page refresh once settings reload.

### 2c. Top-ups for three surfaces the seed doesn't fully cover

The seed has no **earmarks** (there's no create-earmark endpoint — they're service-only),
labels income `freelance`/`employment` rather than the **`self_employment`** the W5
service filters on, and merchant-lifecycle stats are a **snapshot** written by a batch
fit. Run this once to light up the Reliquary bands, the Income plot, and (best-effort)
subscription vitality:

```bash
./.venv/bin/python - <<'PY'
from sqlalchemy import select
from server.src.db.session import SessionLocal
from server.src.db.models import User, Goal, Income
from server.src.services.behavioral import EarmarkService

db = SessionLocal()
user = db.execute(select(User).where(User.username == "demo")).scalar_one()

# (1) Earmarks on the first goal → the Reliquary's liquid bands + Goal Vault jars.
goal = db.execute(
    select(Goal).where(Goal.user_id == user.id).order_by(Goal.id)
).scalars().first()
svc = EarmarkService(db)
for name, cents in [("Rent cushion", 400000), ("Medical", 250000)]:
    try:
        svc.set_earmark(user.id, goal.id, name, cents)  # must be <= goal.progress
    except Exception as e:
        print("earmark skip:", name, e)
db.commit()

# (2) Relabel half the income to self_employment → the Income volatility plot.
incomes = db.execute(select(Income).where(Income.user_id == user.id)).scalars().all()
for i, inc in enumerate(incomes):
    if i % 2 == 0:
        inc.source_type = "self_employment"
db.commit()

# (3) Best-effort merchant-lifecycle fit → subscription vitality gauges.
#     Needs >=5 repeat merchants and PyMC; if it can't fit, the cards simply show
#     WITHOUT the vitality widget (graceful absence — itself a valid QA result).
try:
    from server.src.services.merchant_lifecycle_service import MerchantLifecycleService
    MerchantLifecycleService(db).refresh(user.id)
    db.commit()
    print("lifecycle fit ok")
except Exception as e:
    print("lifecycle fit skipped (graceful):", e)

print("QA top-up done")
PY
```

### 2d. Game mode (for the 3D Reliquary)

Log in → **Settings** → set **game mode** to **`ambient`** or **`full`**. This flips
`<html data-mode>` and turns on `flags.reliquary` → the Goals page renders the 3D
vault. **`off`** mode renders the elevated-2D fallback (and never fetches the three.js
chunk). You'll switch this during the matrix below.

---

## 3. The QA matrix

For each surface: the steps, then the **expected** result. Run the **headline pass**
in `full` mode + Ledger-Paper (light) theme first, then repeat the **cross-cutting
axes** (§4) for the starred ★ surfaces.

### 3.1 ★ The Reliquary — 3D Goal Vault  ·  `/goals`  ·  game mode ambient/full

1. Go to **Goals** in ambient or full mode.
2. Drag to orbit; let it idle.
3. Hover a vessel; click it; press the panel's **Deposit**, **What if…**, **Edit**.
4. Click empty space / press the panel's ✕.

**Expect:**
- A shelf of glass phials, one per goal; fill height = progress/target; the first
  goal shows **colored liquid bands** (the earmarks) with a gold meniscus; the fully
  met goal reads as full.
- Idle **auto-rotate**; hovering **lifts** a vessel; clicking opens a **DOM panel**
  (bottom-center) listing the goal's earmarks + Deposit/What-if/Edit.
- **Deposit** opens the saved-amount dialog; **What if…** routes to `/forecast?goal=…`;
  **Edit** opens the edit dialog (with the auto-fund RuleEditor) → all CRUD works and
  matches the old behavior.
- **Color law:** every dollar figure (vessel caption, panel) is crisp DOM text — **no
  glow, no blur, no game tint on any number**. The canvas paints zero numerals.
- Network tab: the **`Reliquary-*.js` chunk loads only now** (first time Goals mounts
  in ambient/full), not on app boot.

### 3.2 ★ The Almanac  ·  `/almanac`  (Tools nav, every mode)

1. **Spending Atlas** tab: toggle **Spending/Income** and **By month/week/day**.
2. **Net Worth** tab. **Allotment** tab.

**Expect:**
- **Atlas:** an engraved heat-grid (category rows × time columns); cell ink darkens
  with spend, **column-normalized** so a quiet category still reads; right gutter shows
  per-category Σ + a drawn sparkline; foot row = per-bucket totals + grand total.
  Toggling controls refetches without flicker (stale responses are aborted).
- **Net Worth:** an area chart with a gold all-time-high dot + a one-line narrative
  ("growing ~$X/mo · all-time high $Y"); 30/90/365-day delta plates tinted by sign.
- **Allotment:** a % -of-paycheck-allotment meter + ceiling/spent/remaining figures.
- Renders **identically in off mode** (pure finance, no game chrome).

### 3.3 Living Subscriptions + Cadence  ·  `/subscriptions`

1. **Register** tab. 2. **Cadence** tab.

**Expect:**
- **Register:** each mandate shows the periodic charge + a **"Projected / yr"** figure
  (price-creep-adjusted), and the header shows monthly + annual burden. **With
  `MERCHANT_LIFECYCLE_ENABLED` + a successful fit (§2c):** a **Vitality** gauge
  (credit→gold→debit by probability-alive), "~N more charges expected", and an
  **at-risk** section grouped below the active ones. **Without** the fit: cards render
  cleanly *without* those widgets — that's the intended graceful absence, **not a bug**.
- **Cadence:** a forward agenda grouped by month, each row a category swatch + title +
  date + amount on an engraved rail, with monthly subtotals + a 90-day total.

### 3.4 Auditor's Report  ·  the bell (top bar)

1. Open the notification **bell**.
2. Click **"Open full report →"**.
3. If any `rule_proposal`/`rule_suggest` notices exist, hit **Approve** inline.

**Expect:**
- Every notice has a **typed icon + ink** (none falls back to a generic doc icon).
- The full report is a right-side **Sheet** grouping findings by kind (Risk & Drift,
  Budgets, Merchants, Proposals…), each with a deep-link verb or an inline **Approve**
  that mints a token → ConfirmCard → on approve marks read + refreshes.
- (If the demo has no notifications, both the bell and report show the engraved
  "all caught up / nothing flagged" empty states.)

### 3.5 Income volatility  ·  `/income`  (needs `FREELANCER_MODE_ENABLED`)

1. After §2b + §2c, refresh, open **Income** in the nav.

**Expect:**
- A **dispersion chart**: per-month stacked **SE vs W-2** bars, a dashed gold **mean**
  line, and a hatched **buffer cushion** band below the mean.
- A **recommended Safe-to-Spend buffer** figure + a "1-in-N month covered" stamp + a
  one-tap **"Hold back $X"** button. Click it → toast "Buffer set", button → "Buffer
  applied", and Current-buffer figure updates.
- Flag **off** (set `FREELANCER_MODE_ENABLED=false`, restart): the nav entry disappears
  and visiting `/income` shows the "freelancer mode isn't enabled" empty state (the
  endpoint 404s by design).

### 3.6 Agent Vault  ·  Settings → Agent Keys  (needs `MCP_ENABLED`)

1. **`MCP_ENABLED=false`** (restart): Settings → Agent Keys → **"The Bureau is sealed
   shut"** panel.
2. **`MCP_ENABLED=true`** (restart): the full Bureau.
3. To populate the audit ledger, emit a couple of audit rows:

```bash
./.venv/bin/python - <<'PY'
from sqlalchemy import select
from server.src.db.session import SessionLocal
from server.src.db.models import User
from server.src.mcp import audit

db = SessionLocal()
uid = db.execute(select(User).where(User.username == "demo")).scalar_one().id
audit.record(user_id=uid, key_id=1, resource="tx_by_date",
             params={"start": "2026-01-01", "end": "2026-01-31"},
             decision="allow", latency_ms=12.4)
audit.record_failure(reason="rate_limited", key_id=1, user_id=uid)
print("audit rows written")
PY
```

**Expect:**
- A **Capabilities** panel: 5 granted read clauses vs struck-through "Never: write /
  transfer / change a setting".
- An **Audit Ledger**: rows for the reads above — resource label, a `#params_hash`
  fingerprint (never raw params), latency, time, and a **Read/Denied** stamp.
- Issuing/revoking keys still works (the existing Bureau flow is unchanged).

### 3.7 Tax depth  ·  `/tax`  (needs `TAX_FEATURES_ENABLED`)

**Expect:** in the estimated-quarterly card, a **four-plate payment calendar** (Q1–Q4
with date + per-quarter figure, a wax **Seal** on covered quarters, the next-due quarter
ringed in gold, overdue in debit), and **share bars** under each Schedule-C deduction
bucket showing its slice of total deductions.

---

## 4. Cross-cutting checks (run for ★ surfaces, esp. the Reliquary + Almanac)

| Axis | How | Pass criteria |
|---|---|---|
| **Game modes** | Settings → off / ambient / full | Off = pure finance (Reliquary → 2D fallback, no three.js chunk fetched). Ambient/full = 3D + game chrome. No component crashes on switch. |
| **Light / dark** | toggle theme (Settings or the `.dark` class) | Charts + the 3D scene re-ink to the theme (gold→indigo in Midnight). Contrast holds (body text ≥ 4.5:1). |
| **Reduced motion** | OS "Reduce motion" **on**, reload | Reliquary renders **static** (no auto-orbit / wobble), manual orbit still allowed; bars/sparklines/reveals show final state without animating; nothing is hidden. |
| **Color law** | inspect any money figure | No `filter` / `text-shadow` / animation on `.figure` / `.ledger-figures` / `.intaglio`, in 3D captions or 2D. (The guard test covers DOM; eyeball the 3D `<Html>` captions.) |
| **Coarse pointer / touch** | DevTools device toolbar | Reliquary: no drag-orbit/hover, but tap-to-select + the panel work. Tabs/cards reflow; no horizontal scroll at 375px. |
| **Perf (3D)** | DevTools Performance, orbit the vault | ~60fps orbit; GPU memory stable across navigations away/back (geometry disposed). No console errors/WebGL warnings. |
| **No-WebGL** | DevTools → disable WebGL (or a browser without it) | Reliquary falls back to the 2D vault, no crash (error boundary + probe). |
| **A11y** | keyboard + screen reader on Goals + the Sheet | Vault is reachable; the focus panel + dialogs are operable; the Auditor Sheet traps focus and is dismissible. |

---

## 5. Known-deferred — **not bugs**

- **Tax document upload/review** flow is intentionally **not built** this wave (needs the
  heavier propose→confirm machinery). The Tax page's income-by-source still shows
  documented sources; there's just no in-app uploader yet.
- **Per-bucket tax drill-down** (tap a Schedule-C bucket → its transactions) — deferred.
- **Subscription vitality / Income plot** depend on the §2c top-ups (and a working
  lifecycle fit / `self_employment` labels). Their **absence renders gracefully** —
  treat a clean card-without-widget as correct, not a defect.
- The **main JS bundle is ~1.4 MB** (pre-existing single-chunk app). Only the *new* 3D
  code was split out; further main-bundle splitting is out of scope here.

---

## 6. Sign-off checklist

- [ ] App boots; migration at head `a7e920260619`; `demo` login works.
- [ ] Reliquary: 3D vault renders, earmark bands visible, CRUD via panel works, money is clean DOM, chunk lazy-loads.
- [ ] Almanac: heat-grid + net-worth narrative + allotment, all three tabs, off-mode identical.
- [ ] Subscriptions: projected/yr + cadence tab; vitality/at-risk when lifecycle on.
- [ ] Auditor's Report: typed icons, Sheet digest, inline approve.
- [ ] Income: dispersion plot + buffer apply; 404/empty when flag off.
- [ ] Agent Vault: sealed-shut when off; capabilities + audit ledger when on.
- [ ] Tax: quarterly calendar + deduction share bars.
- [ ] Cross-cutting: off/ambient/full × light/dark × reduced-motion all clean; no console errors; no color-law violations.

> Found an issue? Note the surface, mode, theme, and console output. The branch is
> uncommitted — fixes can land before the first commit.
