> **⚠️ SUPERSEDED — 2026-06-17.** The "alive" rollout is complete and Tiers 1–3 shipped & merged to `main` (HEAD `c0e46f6`); current forward work lives in **`HANDOFF-TIER4.md`** (one level up). Kept for its locked design decisions, harness lineage, and precedents.

# Handoff — persFin "alive" frontend rollout (Budgets, Goals, Forecast, + beyond)

> You are a fresh agent with no prior conversation context. This document is
> self-contained: it tells you the goal, where everything lives, the exact pattern
> to apply, how to verify, and what's done vs. pending. Read it fully before editing.
>
> **Date of handoff:** 2026-06-16. **Branch:** `feature/frontend-elevation` (already
> checked out). **Do NOT work on any other branch; do NOT commit to a default branch.**

---

## 0. TL;DR of your job

The team is rolling an "alive but digestible" visual elevation across every real page of
a personal-finance app. Three pages are done (Overview, Accounts, Transactions). **Your
job: apply the same treatment to the remaining pages, one at a time, verifying each in a
browser harness and committing each.** Next up, in order: **Budgets → Goals → Forecast**,
then the rest of the nav (Subscriptions, Reconcile, Tax, and the game pages Keeper/Debts/
Campaigns/Expedition).

The pattern is mostly mechanical and low-risk: swap a page's `<Card>` wrappers to the
`<TiltCard>` component (which adds hover lift + 3D tilt + a cursor-tracking gold sheen),
preserving all existing data/logic/children. A few pages get richer per-page interactions
(see §6).

---

## 1. Where things are (verify before assuming)

- **Repo root for the app:** `Personal-FinanceAPP/` (NOT the workspace root). `package.json`
  + `vite.config.ts` live there. Frontend source is under `Personal-FinanceAPP/client/src/`.
  (There is also a separate OneDrive copy of this project — never touch it; work only in
  this `Personal-FinanceAPP/`.)
- **Backend:** `Personal-FinanceAPP/server/` (FastAPI, `.venv`). You generally do NOT need
  it running — verification uses a no-auth harness with seeded mock data (see §4).
- **Stack:** React 18 + Vite + TypeScript + Tailwind + Zustand store + recharts + Radix UI.
  Routing is `<BrowserRouter><Routes>` in `client/src/main.tsx`.
- **Commands (run from `Personal-FinanceAPP/`):**
  - typecheck: `npx tsc -b`  (MUST stay at 0 errors)
  - build: `npm run build`   (`tsc -b && vite build`)
  - tests: `npx vitest run`  (MUST stay green — currently 41 files / 214 tests pass)
  - dev server: `npm run dev` → http://localhost:5173/
- **Design tokens / global CSS:** `client/src/index.css` (`@layer base/components/utilities`;
  light theme in `:root`, dark theme in `.dark`).
- **The alive card + key components:** `client/src/components/ui/card.tsx` exports `Card`
  (plain), `TiltCard` (alive), and `CardHeader/CardTitle/CardContent/...`.
- **Global atmosphere layers:** `client/src/components/atlas/` — `AtlasLayers.tsx` (mounted
  once in `client/src/components/layout/AppShell.tsx`) composes `GuillocheGL` (WebGL bg),
  `LivingGuilloche` (canvas fallback), `MoodWatermark`, `CursorGlow`, `BurinCursor`.
- **Env hooks:** `client/src/hooks/useEnvironment.ts` → `useReducedMotion()`, `usePointerFine()`.

---

## 2. The design decisions already locked (do not relitigate)

1. **Look = "clean, digestible dashboard that is ALSO alive."** NOT abstract art. The user
   rejected several flashy directions (a physics "living money" organism, a muddy dark
   hero, a 4-style gallery). What landed: clear info hierarchy + rich micro-interactions
   (hover lift/tilt/sheen, reactive cursor-following background glow, count-ups, smooth
   motion on filter/expand). Keep it readable; the motion serves the data, never buries it.
2. **Palette (LOCKED): Ledger Paper = light mode, Midnight = dark mode.** Both live in
   `index.css` (`:root` and `.dark`). Light is the warm cream/teal/gold "Engraver's Ledger";
   dark "Midnight" is a slate base (hue ~222) with an indigo brand accent (244–245). Do not
   change these tokens without explicit user request.
3. **Tech envelope:** Framer **Motion** (`motion/react`) is the everyday animation layer;
   **Lenis** for smooth scroll (mounted in AppShell); **OGL** for the lazy WebGL guilloché;
   **recharts** for charts (already used). Don't add Three.js/GSAP/particle libs.
4. **Color law (non-negotiable):** money figures stay sober — class `.figure` /
   `.ledger-figures` (they carry `filter:none !important`); green = money in, red = money
   out. Amber (`--game-accent`) = the optional game layer; red (`--boss-accent`) = game
   bosses only. Never decorate a real money number with game/WebGL chrome.
5. **Mode discipline:** the app has a game-mode system (`client/src/store/gameMode.tsx`,
   `mode ∈ {off,ambient,full}`). Components read `useFlags()`/`useTerm()`, NEVER branch on
   `mode` directly (a grep test enforces this). The Atlas atmosphere layers are gated to
   ambient+full; `off` stays pixel-honest pure finance. You usually don't touch this — just
   don't violate it.
6. **Accessibility:** every animation needs a reduced-motion fallback. `TiltCard` already
   handles this (renders a plain plate under reduced-motion or non-fine-pointer). Keep AA
   contrast (verified so far). Don't remove focus rings (`:focus-visible` outline in index.css).

---

## 3. THE PATTERN — how to make a page "alive" (do this per page)

**Step 1 — read the page** under `client/src/pages/<Name>/<Name>.tsx` and any card
components it renders (often in `client/src/components/custom/...`). Find every `<Card>` (or
`<Card raking>`).

**Step 2 — swap `<Card>` → `<TiltCard>`** for the content cards:
- Change the import: `import { Card, ... }` → add/relace with `TiltCard` from
  `@/components/ui/card`. If `Card` becomes unused, remove it (tsc will flag it: TS6133).
- Change `<Card ...>` to `<TiltCard ...>` and the matching `</Card>` to `</TiltCard>`.
- `TiltCard` accepts the same `className`/`style`/children as `Card`. It passes them through.
- **Judgment:** use `TiltCard` for discrete content cards (KPIs, stat plates, account cards,
  budget cards). For a TALL scrolling list container, DON'T tilt the whole container (looks
  wrong) — instead make the ROWS alive (the `.ledger-row` class already gives hover-wash +
  manicule + a hover slide; see Transactions precedent in §6).
- Leave empty-state branches as plain `<Card>` if you like (Overview's ExpensesCard keeps a
  plain Card for its empty branch and TiltCard for the populated one — both imports present).

**Step 3 — typecheck:** `npx tsc -b` → fix to 0 errors (usual issue: unused `Card` import).

**Step 4 — VERIFY in the browser** (see §4). Screenshot light AND dark. Confirm: cards
render, money figures still sober, no layout breakage, no JS console errors (CORS errors to
localhost:8000 are EXPECTED and harmless — backend isn't running).

**Step 5 — run tests:** `npx vitest run` → must stay 41 files / 214 passing (or more).

**Step 6 — commit** (only after green + verified). Commit message style:
```
Frontend elevation: <Page> alive

- <what changed>
Verified live in the harness (light+dark). tsc 0; NNN tests pass.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```
Commit each page separately so it's bisectable. Do not push unless the user asks.

---

## 4. THE VERIFICATION HARNESS (how to see pages without auth)

The real pages are behind a login wall and need the backend. To see them without that, a
throwaway dev harness already exists: **`client/src/pages/DevPreview/DevPreview.tsx`**,
routed at **`/dev-preview`** (in `main.tsx`, outside the auth guard). It seeds a broad mock
store (accounts, transactions, budgets, goals, forecast, subscriptions, netWorth, etc.) and
renders any real page via a top switcher, with a light/dark (◐) toggle.

**To verify a page:**
1. Start dev server: `npm run dev` (from `Personal-FinanceAPP/`). It serves on :5173.
   **CRITICAL — it MUST be port 5173.** `client/src/lib/apiBase.ts` only routes API
   calls to the (down) backend on :8000 when `window.location.port === "5173"`. On any
   other port it falls back to `/api`, Vite serves `index.html` for `/api/budgets` (etc.),
   and that HTML string CLOBBERS the seeded store array → e.g. `budgets.map is not a
   function` and an error boundary. If `npm run dev` prints "Port 5173 is in use, trying
   another one…" it has landed on 5174 and the harness WILL break. Fix: find the stale
   server (`lsof -nP -iTCP:5173 -sTCP:LISTEN`), confirm its cwd is THIS `Personal-FinanceAPP/`
   (`lsof -a -p <pid> -d cwd -Fn`) and reuse it, or kill it and restart so you own :5173.
   Never verify on :5174.
2. Use the **chrome-devtools MCP** (already connected in this project, permission-allowed):
   - `mcp__chrome-devtools__new_page` → `http://localhost:5173/dev-preview`
   - `mcp__chrome-devtools__take_snapshot` to get clickable element uids
   - click the page's switcher button (e.g. "Budgets") via `mcp__chrome-devtools__click`,
     or drive state with `mcp__chrome-devtools__evaluate_script`
   - `mcp__chrome-devtools__take_screenshot` then read the saved PNG with the Read tool
   - toggle dark via the ◐ button; screenshot again
   - check `mcp__chrome-devtools__list_console_messages` (ignore CORS/localhost:8000 noise)
3. If a page needs store fields the seed doesn't cover and it renders blank/NaN, ADD those
   fields to `seed()` in `DevPreview.tsx` (match the real type — check `client/src/types/`
   and `client/src/store/store.ts` for shapes; a wrong field name → NaN, as happened once
   with netWorth `value` vs `total`).

**Screenshots save to a temp path** (the tool returns it); Read that path to view inline.

**Cursor/hover effects need a real hover to show** — to demo lift/tilt/expand in a static
shot, dispatch synthetic pointer events / `.click()` via `evaluate_script` before screenshotting
(see how Transactions row-expand was verified). The tab can carry stale `.dark`/scroll state
between calls — set `document.documentElement.classList` explicitly and `window.scrollTo` in
your eval to be deterministic.

---

## 5. STATUS — done vs. pending

**DONE (committed on `feature/frontend-elevation`):**
- Foundation: deps (motion/lenis/d3/ogl), index.css motion tokens + outline focus ring +
  `.plate-raking`/`.plate-tilt` + reduced-motion guards; extended `ModeFlags`; env hooks.
- Atlas layers: `GuillocheGL`, `LivingGuilloche`, `MoodWatermark`, `CursorGlow`, `BurinCursor`,
  composed in `AtlasLayers` and mounted in `AppShell`; Lenis smooth-scroll.
- `TiltCard` = the production alive card (hover lift + spring 3D tilt + cursor gold sheen +
  reduced-motion/touch fallback to a plain plate). In `components/ui/card.tsx`.
- **Palette locked**: `.dark` reskinned to Midnight; light stays Ledger Paper.
- **Overview** page — analytical cards → TiltCard. Verified light+dark.
- **Accounts** page — account cards → TiltCard. Verified.
- **Transactions** page — full treatment: `TransactionItem` rows get desktop-click
  expandable detail (Motion AnimatePresence); `.ledger-row` got a hover slide; existing
  search/account/date filters left intact. Verified.
- **Budgets** page (commit `51ccd25`) — budget plates use `<Certificate>` (NOT `<Card>`),
  so instead of a TiltCard swap, `Certificate` gained an opt-in `alive` prop carrying the
  same alive treatment (spring lift + 3D tilt + cursor gold sheen, reduced-motion/touch
  fallback to the static plate). Budgets passes `alive`; progress bars animate in via
  Motion `whileInView scaleX` (origin-left, reduced-motion renders full). Verified
  light+dark on :5173, hover lift/sheen confirmed, figures sober. `Certificate` is shared
  with Goals — `alive` is default-off so Goals is untouched until step 2 (just add `alive`).
- **Goals** page (commit `ed7b206`) — Certificate cards opt into `alive`; goal progress
  bars animate in. Create/edit/delete/Deposit/What-if flows preserved and verified live
  (card click → Edit; Deposit → its own dialog via stopPropagation; Escape closes). Two
  cross-cutting fixes landed here and are now PRECEDENTS for the rest of the rollout:
  (a) `Certificate` is now `forwardRef` + spreads injected props onto its root, so it is a
  correct Radix `Slot` trigger (Goals wraps it in `DialogTrigger asChild`) — removed a
  "Function components cannot be given refs" warning and restored dialog focus-return;
  (b) **progress/reveal bars must use mount-triggered `animate`, NOT `whileInView`** — a
  below-the-fold card's `whileInView` bar ships BLANK until scrolled into view (caught
  New Laptop at 95% rendering empty). Both Budgets and Goals now use `initial={reduce ?
  false : {scaleX:0}} animate={{scaleX:1}}`. Apply this rule to any future animate-in.

**ROLLOUT DIRECTION CHANGED (2026-06-16):** the user chose to ELEVATE each remaining page
as a real design exercise (varied per-page motion, not a uniform TiltCard swap), holding only
the palette + color law fixed. A shared `components/motion/Reveal.tsx` (stagger primitive,
reduced-motion aware) is the choreography tool; charts/forms get `Card raking` (cursor glow,
no transform — a 3D tilt breaks recharts tooltips & feels wrong under forms), heroes get
`TiltCard`. See memory [[feedback-elevate-rollout-per-page]].

- **Forecast** (commit `eb6584d`) — PromissoryPlate hero → TiltCard; both recharts cards +
  the two control cards → `Card raking`; Projection tab staggered (hero→chart→schedule→
  calendar), What-If/Compare single-block reveal on switch. Seed gap fixed: `forecast.horizon_start`.
- **Subscriptions** (commit `b836bfc`) — mandate cards → TiltCard; CSS stagger → Reveal; added
  a "due soon" chip (within 7d). Seed fixed to real Subscription shape.
- **Reconcile** (commit `3f16cfd`) — both desk cards → `Card raking` (drag-drop dropzone +
  forms, so no tilt); left→right Reveal. Registered Reconcile + Tax in DevPreview PAGES.
- **Tax** (commit `0135691`) — four sections → `Card raking` + column Reveal; estimate hero
  per-quarter → AnimatedNumber. Tax fetches /tax/* via axios (not the store), so DevPreview
  now patches the shared `api.get` to mock /tax/summary + /tax/mileage for the harness.

**PENDING:**
1. **Game pages** — Keeper, Debts, Campaigns, Expedition. These are gated behind game mode
   and carry the color law most heavily (red = bosses only). Lighter priority; confirm with
   the user before doing heavy work here.

**After all pages:** remove the throwaway dev routes + files (see §8) before any merge.

---

## 6. PRECEDENTS to copy (study these exact diffs)

- **Plain card swap:** see how `client/src/components/custom/Overview/SpendCard.tsx`,
  `ExpensesCard.tsx`, `NetWorthCard.tsx`, `TimelineCard.tsx`, `ForecastCard.tsx` changed
  `<Card raking>` → `<TiltCard>` (git log/diff on commits `959c921`, `bf37083`). Same for
  `pages/Accounts/Accounts.tsx` (the mapped account card).
- **Alive rows + expandable detail:** `client/src/components/custom/TransactionItem/
  TransactionItem.tsx` (commit `a369acc`) — desktop click toggles a Motion `AnimatePresence`
  height/opacity detail strip; mobile behavior preserved. Reuse this pattern for any list
  rows (e.g. Subscriptions list).
- **Animated bar (whileInView scaleX):** the `/workspace` dev demo
  (`client/src/pages/Workspace/Workspace.tsx`) shows budget bars, KPI count-ups, and the
  `PopCard`/reactive-bg pattern — a good reference for Budgets/Goals interactions.

`git log --oneline` on the branch shows the full sequence. Read a couple of these commits'
diffs with `git show <hash>` before starting, so your edits match house style.

---

## 7. Larger optional tasks (only if the user explicitly asks)

These are documented but NOT in scope unless requested:
- **Forecast "Sea-Chart"** — a bespoke SVG/d3 chart where the balance is a coastline, the
  `trough_band` confidence interval renders as depth contours, `overdraft_probability` is a
  "sounding", and you can drag the coastline to model what-ifs against `/scenarios/evaluate/`.
  Big task. Spec lives in `~/.claude/plans/the-full-power-of-serene-ember.md` and
  `~/.claude/plans/persfin-motion-and-graphics-language.md`.
- **Command Deck (⌘K)** — the app already has a working `AssistantInterface` (Sheet chat +
  voice + propose→confirm `BridgeCard`). The "Command Deck" is a RESKIN of that into a ⌘K
  surface, NOT a new build. Confirm scope with the user first.
- **Game surfaces** (territory-reclaim Debts, constellation Goals, Cabinet, bestiary) — the
  game-mode visual layer. Confirm before investing.

---

## 8. Cleanup before merge (do last, when user says it's ready)

These throwaway DEV-ONLY routes/files exist for exploration + verification and must be
removed before merging to a real branch (each is flagged `DEV-ONLY, remove after review`):
- routes in `main.tsx`: `/atlas-preview`, `/directions`, `/living`, `/workspace`, `/dev-preview`
- files/dirs: `pages/AtlasPreview/`, `pages/DirectionsGallery/`, `pages/LivingMoney/`,
  `pages/Workspace/`, `pages/DevPreview/` (verify the current set with
  `grep -rn "DEV-ONLY" client/src/main.tsx`).
Removing them must leave `tsc -b` at 0 and tests green.

NOTE: the WebGL guilloché + cursor effects are real production features (in `AtlasLayers`,
gated to ambient/full) — those STAY. Only the preview *pages/routes* above are throwaway.

---

## 9. Working agreement / guardrails (from the user)

- One page at a time; the user wants to SEE each (screenshot light+dark) — show your work.
- Keep `tsc -b` at 0 and `vitest` green at every commit; commit per page; never push unless asked.
- Be honest about what you verified vs. assumed. If you couldn't see something live, say so.
- Don't over-engineer or add complexity the user didn't ask for; the bar is "clean +
  digestible + alive," not "maximal."
- Relevant project memory (auto-loaded): `persfin-frontend-elevation-direction`,
  `persfin-design-prototypes`, `persfin-design-system`, `persfin-dual-tree-layout`,
  `persfin-test-invocation`. Read them if available.
