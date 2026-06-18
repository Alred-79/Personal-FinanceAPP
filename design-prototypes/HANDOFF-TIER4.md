# Handoff — Tier 4 (richer interactions)

> You are a fresh agent with no prior conversation context. This document is
> self-contained: goal, where everything lives, the exact patterns, how to
> verify (READ §2 CAREFULLY — the old screenshot harness was deleted), the
> locked guardrails, and the four Tier 4 tasks with concrete starting points.
> Read it fully before editing.
>
> **Date:** 2026-06-17. **App root:** `Personal-FinanceAPP/`. Tiers 1–3 of
> `design-prototypes/HANDOFF-NEXT.md` are DONE, **merged to `main`, and pushed**
> (origin `github.com/Alred-79/Personal-FinanceAPP`, HEAD `c0e46f6`). Tier 4 is
> the last bucket in `HANDOFF-NEXT.md` and was **explicitly deferred** — confirm
> with the user which item(s) they want before a large build.

---

## 0. What Tier 4 is

From `HANDOFF-NEXT.md` §"TIER 4 — richer interactions (optional / ambitious)":

1. **Command Deck** — today the ⌘K palette is **nav-only**. The fuller vision is
   a command deck that also runs **actions** (add transaction, link bank, jump to
   a scenario) — a *reskin/merge of the existing assistant machinery*, NOT a new
   engine. Prototype: `design-prototypes/page-command-deck.html`.
2. **AssistantInterface / Chronicler** — the AI chat surface (Sheet + voice +
   propose→confirm). Design polish + the Command-Deck integration above.
3. **Notifications** (`NotificationBell`) — surface + a fuller center design.
4. **Cashflow Timeline** (Overview) — works as designed (income up / bills down on
   a signed axis) but reads oddly with sparse data; plot positive magnitudes or
   enrich the forward income/bill series.

These are independent. The **Command Deck is the headline** and the most work;
the **Cashflow Timeline is the smallest, self-contained win**.

---

## 1. Repo, stack, commands

- **App root:** `Personal-FinanceAPP/` (NOT the workspace root). Frontend under
  `Personal-FinanceAPP/client/src/`. Backend under `Personal-FinanceAPP/server/`
  (FastAPI, a local `.venv` — there is **no pipenv**; call `.venv` binaries directly).
- **Stack:** React 18 + Vite + TS + Tailwind + Zustand store + Radix UI + recharts
  + Framer **Motion** (`motion/react`) + Lenis smooth-scroll + OGL (lazy WebGL).
  **No new deps** — the engraving/motion toolkit covers Tier 4.
- **Commands (run from `Personal-FinanceAPP/`):**
  - typecheck: `npx tsc -b` — **MUST stay 0**.
  - tests: `npx vitest run` — **MUST stay green: 41 files / 214 tests** as of HEAD.
  - build (the real merge gate): `npm run build` (`tsc -b && vite build`).
  - client dev: `npm run dev` → http://localhost:5173/ (**must be 5173** — see §2).
  - backend dev: `./.venv/bin/uvicorn server.src.main:app --reload` → :8000.
  - backend tests: `./.venv/bin/pytest -q`.
- **Routing:** `<BrowserRouter><Routes>` in `client/src/main.tsx`. Public routes:
  `/welcome` (landing) + `/login`. Everything else is under `ProtectedRoute` →
  `AppShell`. `ProtectedRoute` gates on `isLoggedIn` in the Zustand store and
  redirects signed-out users to `/welcome`.
- **Global CSS / tokens:** `client/src/index.css` (`:root` light = "Ledger Paper",
  `.dark` = "Midnight"; game tokens `--game-accent` amber, `--boss-accent` red).
- **Git:** everything is on `main` and pushed. **Branch off `main`** for Tier 4
  (`git checkout main && git pull && git checkout -b feature/tier4-<thing>`).
  Commit per surface; **do not push or merge unless the user asks**.

---

## 2. ⚠️ VERIFICATION — the screenshot harness was DELETED

Tiers 1–3 were verified in a throwaway `/dev-preview` harness that rendered pages
without auth or backend. **It was removed in the pre-merge cleanup (commit
`c0e46f6`).** There is no `/dev-preview` route or `DevPreview.tsx` anymore. You
have two options:

### Option A — run the real stack (recommended for Tier 4)
Tier 4 is **backend-coupled** in a way Tiers 1–3 were not: the Command Deck and
Assistant stream SSE, POST proposals, and round-trip `confirm` tokens;
Notifications poll an endpoint. A static harness can't exercise those. So:
1. Start the backend: `./.venv/bin/uvicorn server.src.main:app --reload` (:8000).
   It must allow CORS from `http://localhost:5173` (it's configured for dev).
2. Start the client: `npm run dev` (**:5173** — `client/src/lib/apiBase.ts` only
   points at `http://localhost:8000/api` when `window.location.port === "5173"`;
   on any other port it falls back to `/api` and the app breaks).
3. Open http://localhost:5173/login, **sign up** (creates a user) or log in, then
   drive the real app. Use the **chrome-devtools MCP** (permission-allowed) to
   click/snapshot/screenshot, exactly as the prior handoffs describe.

### Option B — re-add a minimal visual harness (for pure-visual bits only)
Good enough for the Notifications popover and the Timeline chart, NOT for live
SSE/proposals. Recreate a throwaway `pages/DevPreview/DevPreview.tsx` + a
`/dev-preview` route in `main.tsx` (flag both `// DEV-ONLY, remove after review`).
The deleted one did exactly this — reconstruct it from these notes:
- A `PAGES` registry of `lazy(() => import(...))` page components + a top button bar.
- A `seed()` that does `useStore.setState({ isLoggedIn:true, userLoaded:true, accounts, transactions, budgets, goals, forecast, notifications, … })` to match the store's real types (`client/src/types/`, `client/src/store/store.ts`). A wrong field name renders NaN/blank.
- A light/dark toggle (`document.documentElement.classList.toggle('dark')`).
- A game-mode switch: `const { mode, setMode } = useGameMode()` + off/ambient/full
  buttons (DevPreview renders inside `GameModeProvider`, so `setMode` works; it
  optimistically switches locally and swallows the failed `PUT /settings`).
- Mock backend GETs by monkey-patching the shared axios instance:
  `const orig = api.get.bind(api); (api as any).get = (url) => url.startsWith('/notifications') ? Promise.resolve({data: MOCK}) : orig(url)`.
- Expose the store for driving states: `(window as any).__useStore = useStore`.
- **Gotcha:** game pages (`Keeper/Debts/Campaigns`) `<Navigate to="/settings">` in
  off mode; with `isLoggedIn:true` seeded that navigates the REAL app. Set game
  mode to `full`/`ambient` and **wait for `document.documentElement.dataset.mode`
  to update before** switching to a game page, or you drift out of the harness.
- **Remember to delete it again before any merge** (add it to the §8 cleanup list).

Whichever you use: screenshot **light + dark**, keep `tsc` at 0 and tests green,
and be honest about what you verified live vs. assumed.

---

## 3. NON-NEGOTIABLE guardrails (carry forward)

- **Palette LOCKED:** Ledger Paper (light) / Midnight (dark). Don't change tokens.
- **Color law:** money figures stay sober (`.figure` / `.ledger-figures`, which
  carry `filter:none !important`); green = money in, red = money out; **amber
  (`--game-accent`) = the game layer only**; **red (`--boss-accent`) = bosses
  only**, never a user number. The Command Deck's action chrome = **gold**, never
  decorate a money figure with it.
- **Mode discipline:** components read `useFlags()` / `useTerm()` / `<Term/>`,
  **never branch on `mode` directly** (a grep test enforces this). `commandDeck`
  is a flag that is **true in every mode** (it's a finance tool, not game chrome).
- **Motion envelope:** Motion for everyday animation, Lenis for scroll, OGL for the
  lazy guilloché. Every animation needs a **reduced-motion** fallback
  (`useReducedMotion()` from `hooks/useEnvironment`). Keep `:focus-visible` gold
  outline rings. Touch / coarse-pointer must stay usable (no hover-only actions).
- **Don't break tests / testids.** Many surfaces carry `data-testid`s asserted by
  tests; preserve them when restyling. `grep -rn "data-testid" <file>` first.
- **Per surface:** treat each as a real design exercise (vary motion; don't reflex
  the same hover everywhere); verify live; commit per surface. See memory
  `feedback-elevate-rollout-per-page`.

---

## 4. The four tasks (files, goal, approach, gotchas)

> **The propose→confirm machinery already EXISTS.** Tier 4's Command Deck is a
> *reskin + merge*, not a new engine. Read these before designing:

- `components/custom/NavPalette/NavPalette.tsx` — the ⌘K palette. Props
  `{ open, onOpenChange }`. A shadcn `Dialog` at `top-[18%]`; a search input;
  destinations from `NAV_ITEMS` (`components/layout/nav.ts`) grouped by
  `NAV_GROUPS` (ledger/tools/game), filtered by `useFlags()` (`gameLayer`) and the
  tax flag; ↑/↓/Enter/Esc keyboard nav; `go()` closes + `navigate(item.to)`.
  **Nav-only today** — no actions.
- `components/layout/Header.tsx` — owns `paletteOpen`, the ⌘K/Ctrl-K key handler,
  the "Jump to…" button, and mounts `<NavPalette>`.
- `components/custom/AssistantInterface/AssistantInterface.tsx` — the assistant
  **Sheet** (floating MessageCircle button), SSE chat (`/assistant/chat/`), voice
  (`/assistant/transcribe`), and the propose→confirm event handling. Mounted in
  `AppShell`.
- `components/custom/BridgeCard/BridgeCard.tsx` — the assisted-action card
  (propose → record → "I did it ✓"); `confirm_token` → `/assistant/actions/confirm/`
  then `/assisted-actions/{id}/done/`.
- `components/custom/ConfirmCard/ConfirmCard.tsx` — shared approve/decline card;
  POSTs `/assistant/actions/confirm/` with a `token`; shows a `Seal` on success.
  Reused by AssistantInterface, Forecast (what-if commit), Goals.
- `components/custom/ChroniclerDrawer/ChroniclerDrawer.tsx` — the game-mode chat
  drawer, opened by the `/` key; POSTs `/game/chronicler/ask/`. Separate from the
  main assistant.
- `store/store.ts` — Zustand actions you'll likely call (`addTransaction`,
  `fetchAccounts`, notifications actions, etc.). Verify names before assuming.

### TASK 1 — Command Deck (LARGE; confirm scope first)
Make the ⌘K surface run **actions**, not just navigate. The prototype
`design-prototypes/page-command-deck.html` shows the design: the page recedes
behind a veil, a centred "deck" overlay inks in, you type an intent, an agent
reply inks in, and a **propose→confirm diff plate** stamps on approve.
- **Approach:** extend `NavPalette` (or a new `CommandDeck` that supersedes it)
  so its result list mixes **destinations** (existing `NAV_ITEMS`) with **actions**
  (add transaction, link bank → the Plaid handler in `Header`/`Sidebar`, jump to a
  scenario in Forecast). For agent-style intents, **reuse the existing
  AssistantInterface pipeline + `ConfirmCard`/`BridgeCard`** rather than building a
  new one — the deck is a new *entry point* + skin over machinery that already works.
- **Gotchas:** `commandDeck` flag is on in every mode (don't gate it to game).
  Keep ⌘K + the "Jump to…" button working. Actions that move money MUST go through
  the propose→confirm (`ConfirmCard`) path — never fire a mutation straight from a
  palette row. Keyboard-first + reduced-motion. Don't regress nav filtering by mode/tax.

### TASK 2 — Assistant / Chronicler polish
Design polish on `AssistantInterface` + `ChroniclerDrawer` (spacing, message
typography, the voice affordance, the propose→confirm cards' visual weight), and
the integration with the Command Deck (one coherent surface, not two). Preserve
the SSE event handling and all action tokens. This pairs naturally with Task 1.

### TASK 3 — Notifications center
`components/custom/NotificationBell/NotificationBell.tsx` — today a bell + badge +
a Popover list (`notifications`, `unreadCount`, `fetchNotifications`,
`markNotificationRead`, `markAllNotificationsRead` from the store; polls ~60s).
Design a fuller **center**: grouped/typed notices (budget_overrun, anomaly, …),
read/unread treatment, empty state (reuse `components/engraving/EmptyState.tsx`),
and per-item actions/deep-links. Keep the badge + mark-read behavior and any testids.

### TASK 4 — Cashflow Timeline (smallest; good first surface)
`components/custom/Overview/TimelineCard.tsx` — a recharts `ComposedChart` with
`stackOffset="sign"`: past `spent` as an Area (debit), forward `projIncome` (up,
credit) / `projExpense` (down, debit) as Bars, a gold "today" ReferenceLine. It
reads `recentTransactions` + `forecast.timeline` from the store. **Why it reads
oddly:** with sparse forward data the signed axis stretches and the bars look lost.
- **Approach options (pick one, keep the color law):** plot **positive magnitudes**
  with direction shown by color/position instead of a signed axis; OR enrich the
  forward series (carry the running projected balance as the Area, bills/income as
  markers); OR add a graceful empty/low-data state. Verify with both rich and
  near-empty forecast data.

---

## 5. Reusable primitives (REUSE — don't reinvent)

- **Cards:** `components/ui/card.tsx` → `Card` (plain), `Card raking` (cursor
  desk-lamp glow, no transform — right under forms/charts), `TiltCard` (3D tilt +
  gold sheen — heroes only). All reduced-motion/touch aware.
- **Engraving:** `components/engraving/` → `Certificate` (alive plate), `Seal`
  (medallion, tones wax/approved/void, pulse), `Stamp`, `Guilloche`/`GuillocheBand`/
  `CornerRosette`, `AnimatedNumber`, `Figure`, `Sparkline`, `SectionRule`,
  `EmptyState` (no-data showpiece: framed plate + motif + CTA), `Brandmark`.
- **Motion:** `components/motion/Reveal.tsx` → `Reveal` + `RevealItem` (mount or
  scroll stagger, reduced-motion safe).
- **Game-layer (Tier 3, for reference/patterns):** `components/custom/BossTerritory`
  (in Debts), `components/custom/Bestiary/BestiaryCreature` (in Debts),
  `components/custom/VoyageMap` (in Expedition), `components/custom/MintedCoin`
  (in the Goals Cabinet). All are DPR-aware canvases / seeded SVGs / coins that show
  how to do reduced-motion-safe `<canvas>` + Motion in this codebase.
- **Nav:** `components/layout/nav.ts` (`NAV_ITEMS`, `NAV_GROUPS`),
  `SidebarRail`, `Header`, `NavPalette`.
- **Env hooks:** `hooks/useEnvironment.ts` → `useReducedMotion()`, `usePointerFine()`.

---

## 6. Working agreement (from the user)

- One surface at a time; the user wants to SEE each (screenshot light + dark).
- Keep `tsc -b` at 0 and `vitest` green (41/214) at every commit; commit per surface.
- **Never push or merge unless explicitly asked.** Branch off `main`.
- Be honest about what you verified live vs. assumed. If you couldn't see SSE/
  proposals without the backend, say so.
- Don't over-engineer; the bar is "clean + digestible + alive," not "maximal."
- If you re-add any DEV-ONLY harness/route, flag it `// DEV-ONLY, remove after
  review` and remove it before any merge.

---

## 7. Pointers
- The four prototypes for Tier 4 / context: `design-prototypes/page-command-deck.html`
  (Command Deck), plus `dynamic.html` (the v2 baseline these extend),
  `DESIGN-LANGUAGE.md`, `core-ambient.html`.
- Locked decisions, the alive pattern, harness lineage: `HANDOFF-PHASE4-ROLLOUT.md`;
  the Tier 1–3 backlog + what shipped: `HANDOFF-NEXT.md`.
- Project memory worth reading first (auto-loaded if present): `persfin-tier12-shipped`
  (Tiers 1–3 + this merge/push state), `persfin-frontend-rollout-budgets`,
  `feedback-elevate-rollout-per-page`, `persfin-frontend-elevation-direction`,
  `persfin-design-system`, `persfin-voice-input` (the transcribe flow),
  `persfin-test-invocation`.

---

## 8. If you add a harness or any dev route — cleanup before merge
Mirror the Tier 1–3 hygiene: remove every `// DEV-ONLY` route in `main.tsx` + its
page dir, leave `tsc -b` at 0 and tests green, run `npm run build` clean, and only
merge/push when the user says so. (The previous round's cleanup was commit `c0e46f6`.)
