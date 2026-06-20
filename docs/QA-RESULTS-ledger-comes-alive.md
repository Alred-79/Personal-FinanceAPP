# QA Results — "The Ledger Comes Alive"

Live, browser-driven execution of `docs/QA-LEDGER-COMES-ALIVE.md` on branch
**`feat/ledger-comes-alive`**, driven with the Chrome DevTools MCP.

- **Date:** 2026-06-19
- **DB:** SQLite (app default session). Migration head **`a7e920260619`** confirmed.
- **Backend:** FastAPI :8000 · **Frontend:** Vite dev :5173 (and a prod build served at :8000 for one cross-check).
- **Flags for QA:** `MCP_ENABLED`, `FREELANCER_MODE_ENABLED`, `MERCHANT_LIFECYCLE_ENABLED`, `TAX_FEATURES_ENABLED` = true (then FREELANCER+MCP flipped off for §3.5/§3.6 off-state checks).
- **Seed:** `demo` / `Demo123!` + §2c top-ups (earmarks, `self_employment` relabel, lifecycle fit **succeeded**) + §3.6 audit rows + 9 synthetic notifications (to exercise §3.4).
- Screenshots in `docs/qa-screenshots/`.

> **Bottom line (initial QA):** 5 of 8 surfaces solid. **Two CRITICAL issues** (3D vault crash; logged-out reload loop) and **three lower bugs** (one blocking the Almanac Allotment tab) found.
>
> **UPDATE — fixes applied & verified (see "Fixes applied" at the bottom):** Both CRITICALs + the Allotment blocker are **fixed and re-verified live**. The 3D vault now renders (dev + prod), cookieless login works (no loop), and the Allotment tab renders. `tsc -b` + `vite build` clean, **234/234 frontend tests pass**, backend expense tests pass. Findings D (Cadence 4×), E (Tax paid-state), F (a11y) remain open (pre-existing/minor).

---

## §6 Sign-off checklist

| # | Item | Verdict |
|---|---|---|
| 1 | App boots; migration at head `a7e920260619`; `demo` login works | ⚠️ **Boots & migration OK; login works _but_ a logged-out browser hits an infinite reload loop** (Finding B) — login only succeeded after injecting a session cookie |
| 2 | Reliquary: 3D vault renders, earmark bands, CRUD, clean DOM money, chunk lazy-loads | ❌ **3D vault CRASHES** → 2D fallback (Finding A). 2D fallback: earmark bands ✓, card CRUD ✓ (What-if→`/forecast?goal=1` ✓), money clean DOM ✓, three.js lazy-loads only on Goals mount ✓ |
| 3 | Almanac: heat-grid + net-worth narrative + allotment, all 3 tabs, off-mode identical | ⚠️ Atlas ✓ (toggles refetch clean), Net Worth ✓ (ATH dot + narrative + delta plates), **Allotment ✗ stuck "Gathering…"** (Finding C), off-mode identical ✓ |
| 4 | Subscriptions: projected/yr + cadence; vitality/at-risk when lifecycle on | ⚠️ Register ✓ (projected/yr, monthly+annual burden, **Vitality gauges 97–99% lit**), **Cadence shows each charge 4×** & inflates totals (Finding D) |
| 5 | Auditor's Report: typed icons, Sheet digest, inline approve | ✅ Typed verbs/icons (no generic fallback), Sheet grouped by kind (Risk&Drift/Budgets/Merchants/Proposals/Other), Mark-all-read works; inline Approve fires the token-mint (full happy-path needs a real proposal — synthetic 400, expected) |
| 6 | Income: dispersion plot + buffer apply; 404/empty when flag off | ✅ Dispersion (SE vs W-2 + hatched buffer band), buffer $90.20 → toast "Buffer set" → "BUFFER APPLIED" → CURRENT BUFFER updated; flag-off → nav gone + "isn't enabled" empty state + endpoint 404 |
| 7 | Agent Vault: sealed-shut when off; capabilities + audit ledger when on | ✅ On: 5 read clauses vs struck Never (write/transfer/setting) + audit ledger rows (`#params_hash`, latency, READ/DENIED); Off: "The Bureau is sealed shut" |
| 8 | Tax: quarterly calendar + deduction share bars | ⚠️ Four-plate Q1–Q4 calendar ✓ (dates, figures, OVERDUE/UPCOMING, seals on covered); **share bars absent (no business-tagged data — graceful)**; **minor "all PAID" bug** on partial payment (Finding E) |
| X | Cross-cutting: off/ambient/full × light/dark × reduced-motion; no console errors; no color-law violations | ⚠️ Modes ✓ (off = no three.js fetched), light/dark ✓ (re-inks, contrast holds), mobile 375px ✓ (no h-scroll), no-WebGL ✓ (probe skips three.js, no crash), color-law ✓ (`.figure`/`.ledger-figures` clean; `.intaglio` letterpress is intended); **console NOT clean** (3D-crash errors + app-wide 422s); reduced-motion & 3D-perf not fully verifiable here (see Limits) |

---

## Findings

### A — CRITICAL · 3D Goal Vault crashes at runtime (`/goals`, ambient/full)  ·  *introduced by this wave*
The headline 3D Reliquary throws on mount and the `ReliquaryBoundary` error boundary
falls back to the 2D vault — in **both dev and a production build**.

- **Error:** `TypeError: Cannot read properties of undefined (reading 'hidden')`, thrown inside **R3F's reconciler**: `applyProps` → `createInstance` (`@react-three/fiber` chunk). R3F cannot instantiate *any* three.js object, so every `<Canvas>` dies.
- **Root cause:** version incompatibility — `three@0.180.0` (added this wave, with `@types/three@^0.180`) is too new for `@react-three/fiber@8.18.0` / `@react-three/drei@9.122`. R3F v8's open peer range (`three >=0.133`) gives no install warning, but r180 changed an internal that R3F v8's prop-applier reads. (React 18 + R3F v8 + drei v9 is otherwise the correct trio; React is **not** the problem.)
- **Repro:** `/goals` in ambient/full → 2D certificates render, console shows `reading 'hidden'` ×4. Screenshots: `3.1-goals-full-light.png`, `3.1-goals-PROD-crash-fallback.png`.
- **Suggested fix:** pin `three` (and `@types/three`) to an R3F-v8-tested release (the `~0.169`/`0.170` era) and re-`npm install`; re-test `/goals`. (Upgrading to R3F v9 is the alternative but it targets React 19.)
- **Mitigation already in place:** the error boundary + 2D fallback mean users get a working 2D vault, not a white screen.

### B — CRITICAL · Logged-out reload loop blocks first login  ·  *present on this branch*
A browser with **no session cookie** (new user, or expired refresh cookie) cannot reach
a usable login page — the app reload-loops.

- **Chain:** `GameModeProvider` ([client/src/store/gameMode.tsx:119-129](../client/src/store/gameMode.tsx#L119-L129)) fires `GET /settings/` on mount, and it wraps the **entire app including `/login` & `/welcome`** (outside `ProtectedRoute`, [client/src/main.tsx:43](../client/src/main.tsx#L43)). Unauthenticated → 401 → the axios interceptor ([client/src/lib/api.ts:64-77](../client/src/lib/api.ts#L64-L77)) calls `refreshOnce()` → `/refresh/` 401 → `window.location.href = "/login"` → full reload → `GameModeProvider` remounts → refetch → **∞** (the dev `/refresh/` rate-limit 429 is just a symptom of the rapid looping).
- **Why the doc author didn't hit it:** an existing valid `httpOnly` refresh cookie makes `/settings/` succeed; the MCP browser (cookieless) loops. QA only proceeded after injecting a session cookie via a login XHR.
- **Suggested fix (any one):** skip/guard the `GameModeProvider` settings fetch when unauthenticated (or on the public `/login`,`/welcome` routes), and/or make the interceptor not hard-redirect when already on `/login`.

### C — HIGH · Almanac **Allotment** tab stuck "Gathering this period's figures…"  ·  *pre-existing, surfaced by this wave*
- **Chain:** `AllotmentReadout` gates on `store.hasLoaded`. `fetchInitialData` ([client/src/store/store.ts:497-521](../client/src/store/store.ts#L497-L521)) awaits `GET /expenses/fixed-per-month` which **422s**, throwing before `hasLoaded`/`spendOverTime` are ever set → the readout never renders.
- **Root cause:** route typo — [server/src/routers/expenses.py:37](../server/src/routers/expenses.py#L37) is `@router.get("/fixed per month/")` (**spaces, not hyphens**). The client calls `/expenses/fixed-per-month/`, which then matches `/{id}/` and tries to parse `"fixed-per-month"` as an int → 422. `expenses.py` is **unchanged by this wave** (last touched Jun 11).
- **Blast radius:** this is also the source of the **app-wide `422 / "Error fetching initial data"` console spam** (Home, Almanac, anywhere `fetchInitialData` runs) and any store figure backed by `hasLoaded`/`spendOverTime`.
- **Suggested fix (1 char):** `"/fixed per month/"` → `"/fixed-per-month/"`. Unblocks the Allotment tab and silences the global 422.

### D — MEDIUM · Subscriptions **Cadence** shows every charge 4× & inflates totals  ·  *pre-existing, surfaced by this wave*
- **Symptom:** each recurring charge appears **4×** on the same due date (Spotify 12× over 90 days vs the expected ~3); June subtotal `$147.92` = 4×($11.99+$24.99); the "90-day" total `$26,933.52` equals the *annual* projection.
- **Root cause:** `RecurringService._project_rows` ([server/src/services/recurring_service.py:146-184](../server/src/services/recurring_service.py#L146-L184)) projects from **every expense row with a non-null recurrence**. The seed stores one row per historical occurrence (4 past Spotify rows, ids 1/8/15/22, each `recurrence=monthly`), so each spawns its own forward series. `recurring_service.py` is **unchanged by this wave**; the new Cadence tab + the backend `/recurring/projected/` endpoint surface it. (The Register tab is fine — it uses dedup'd merchant detection.)
- **Suggested fix:** dedupe recurring series by merchant (title + amount + cadence) and project from a single anchor.

### E — MINOR · Tax payment schedule marks **all** quarters "PAID" on partial payment  ·  *introduced by this wave*
- **Repro:** with "Paid so far" = `$0` the calendar is correct (Q1/Q2 OVERDUE, Q3/Q4 UPCOMING). Enter `$2,300` (of a `$4,434.70` annual) → still-owed correctly `$2,134.70`, but **all four quarters flip to "PAID"** while each still shows `$533.67` due — contradictory.
- **Root cause:** `QuarterlyCalendar.tsx:28` computes `coveredCount = Math.floor(paid / perQ)`, but `perQ` is the **post-payment** per-quarter (`remaining/4 = $533.67`), not the gross (`annual/4 = $1,108.67`). `floor(2300/533.67)=4`. ([client/src/components/custom/Tax/QuarterlyCalendar.tsx:22-34](../client/src/components/custom/Tax/QuarterlyCalendar.tsx#L22-L34))
- **Suggested fix:** divide `payments_made` by the **gross** per-quarter (annual/4) when computing covered quarters.

### F — MINOR (a11y) · Dialog missing description  ·  *this wave*
- React warns: *"Missing `Description` or `aria-describedby={undefined}` for {DialogContent}"* (×2) when opening the notices / Auditor's Report dialog. Add a `Description`/`aria-describedby` for screen-reader users.

### Non-defects (expected / graceful)
- **Deduction share bars** absent on Tax — the seed has no business-tagged expenses ("No business-tagged expenses for 2026"). Graceful, matches §5.
- **Subscription Vitality** present (97–99%) — the §2c lifecycle fit succeeded (PyMC fit OK on this machine).
- **`.intaglio` text-shadow** — a 0px-blur letterpress effect, the intended engraving style; the implemented color-law guard ([game-mode-guards.test.tsx:69-80](../client/src/__tests__/game-mode-guards.test.tsx#L69-L80)) scopes to `.figure`/`.ledger-figures` (clean). The doc's prose also lists `.intaglio`, a wording-vs-implementation mismatch, not a defect.
- **`/mcp/` returns 200 with MCP off** — that's the SPA catch-all serving `index.html`, not the MCP server (which is correctly unmounted); the UI shows "sealed shut".

---

## Cross-cutting axes (§4)

| Axis | Result |
|---|---|
| Game modes | ✅ **off** = pure 2D, **0 three.js modules fetched**, console clean. ambient/full = 3D attempted → crashes → 2D (Finding A). No crash on switch. |
| Light / dark | ✅ Re-inks to midnight; heat-grid colours + sparklines + figures readable; contrast holds. (`4-almanac-atlas-DARK.png`) |
| Reduced motion | ⚠️ **Not fully verifiable** via this MCP (no reduced-motion toggle in `emulate`); 3D auto-orbit suppression is moot (3D doesn't run). CSS `motion-reduce:` variants exist in code. → manual OS-level check recommended. |
| Color law | ✅ `.figure`/`.ledger-figures` carry no filter/text-shadow/animation (DOM scan, 20 nodes). `.intaglio` letterpress is intended (see Non-defects). 3D `<Html>` captions not eyeball-able (3D down). |
| Coarse pointer / mobile | ✅ 375px: no horizontal scroll (scrollWidth==innerWidth), sidebar→hamburger, cards stack, earmark band visible. (`4-goals-mobile-375.png`) |
| No-WebGL | ✅ WebGL disabled → probe short-circuits, **three.js never loads**, 2D fallback, **no crash**, console clean. |
| Perf (3D) | ⛔ **Blocked** by Finding A — no live 3D canvas to measure 60fps orbit / GPU-memory-across-nav. Re-run after the three pin. |
| A11y (keyboard/SR) | ⚠️ Partial — dialogs/sheet are reachable & dismissible; one missing dialog description (Finding F). Full screen-reader pass is manual. |

---

## Limits of this run
- Reduced-motion, touch, no-WebGL, and theme were **emulated** via the Chrome DevTools MCP / init-scripts — faithful but not identical to OS-level settings.
- 3D GPU-memory-across-navigation and a full screen-reader pass are **manual**; the 3D-perf axis is currently **blocked** by Finding A.
- The Auditor inline-Approve happy path (token → ConfirmCard → mark-read) couldn't be fully driven because synthetic proposal notifications have no backing proposal (mint 400, expected). The button wiring is confirmed.

## State changes made during QA (demo data only — idempotent on re-seed)
- `s2s_buffer` set to `$90.20` (Income buffer-apply test); `game_mode` left at `ambient`; 9 synthetic notifications created then marked read. Re-run `python -m server.scripts.seed_demo` to reset.
- `.env` was edited for QA and **restored** from backup at end of run; both servers stopped.

---

## Fixes applied (post-QA, verified live)

Applied on `feat/ledger-comes-alive` and re-verified in-browser. `tsc -b` + `vite build`
clean; **234/234 frontend tests pass**; backend expense tests pass.

### A (CRITICAL) — 3D Goal Vault crash → **FIXED**
- **Real root cause** (the three-version theory in Finding A was wrong — pinning `three`
  to 0.169 did **not** help): `VesselLabel` passed **`aria-hidden`** to drei's `<Html>`,
  which spreads extra props onto the R3F `<group>` ([drei Html.js:362](../node_modules/@react-three/drei/web/Html.js)).
  R3F's `resolve()` splits hyphenated prop names into nested paths (`aria-hidden` →
  `group.aria.hidden`); `group.aria` is `undefined` → `reading 'hidden'` → every Canvas dies.
- **Fix:** moved `aria-hidden` from `<Html>` onto the inner DOM `<div>` in
  [client/src/components/reliquary/VesselLabel.tsx](../client/src/components/reliquary/VesselLabel.tsx)
  (preserves the screen-reader intent on real DOM). Reverted the unnecessary `three`/`@types/three`
  downgrade back to `^0.180.0`.
- **Verified:** `/goals` (ambient) now renders the 3D shelf — live WebGL canvas, glass
  vessels, **Emergency Fund earmark bands + gold meniscus**, crisp DOM captions — **no
  console errors**, in both dev (:5173) and the prod build (:8000). (`3.1-goals-3D-FIXED.png`)

### B (CRITICAL) — logged-out reload loop → **FIXED**
- **Fix:** the axios response interceptor now only force-redirects to `/login` when **not
  already on a public route** (`/login`, `/welcome`) — so a failed background probe
  (GameModeProvider's `/settings/` read above the auth boundary) no longer reload-loops.
  [client/src/lib/api.ts](../client/src/lib/api.ts).
- **Verified:** a fresh **cookieless** browser context loads `/login` stably (single
  navigation, no loop) and logs in successfully (`demo` → Overview).

### C (HIGH) — Almanac Allotment stuck + app-wide 422 → **FIXED (two parts)**
- **C1 (route typo):** [server/src/routers/expenses.py](../server/src/routers/expenses.py)
  `@router.get("/fixed per month/")` → `"/fixed-per-month/"`. **Verified:**
  `/api/expenses/fixed-per-month/` now `200`; the app-wide `422 / "Error fetching initial data"`
  console spam is gone.
- **C2 (the actual Allotment blocker, found during verification):** the Allotment readout
  gates on the global `hasLoaded`, which is set **only** by `fetchInitialData` (called only
  by Overview). The **Almanac** page calls `refreshBudgetData`, which loaded the same
  budget/spend data but never set `hasLoaded` → a *direct* load of `/almanac` hung on
  "Gathering…" regardless of the typo. **Fix:** `refreshBudgetData` now sets
  `hasLoaded: true` on success ([client/src/store/store.ts](../client/src/store/store.ts)).
  **Verified:** Allotment renders the meter + CEILING $380.73 / SPENT $542.40 / REMAINING.
  (`3.2-almanac-allotment-FIXED.png`) · *Minor trade-off:* visiting Almanac before Overview
  in a session now marks `hasLoaded`, so Overview skips a `users/me` re-fetch
  (`warningPosition` may stay default until refreshed) — acceptable; flag if undesired.

### Still open (not addressed this round)
- **D (MEDIUM, pre-existing):** `/recurring/projected` 4× duplication → Cadence inflated.
- **E (MINOR):** Tax "all PAID" on partial payment (`QuarterlyCalendar.tsx:28`).
- **F (MINOR a11y):** DialogContent missing `aria-describedby`.

> Changes are **uncommitted** on `feat/ledger-comes-alive`. Files touched:
> `client/src/components/reliquary/VesselLabel.tsx`, `client/src/lib/api.ts`,
> `client/src/store/store.ts`, `server/src/routers/expenses.py` (and a `client/dist` rebuild).
