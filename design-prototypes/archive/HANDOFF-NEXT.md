> **⚠️ SUPERSEDED — 2026-06-17.** Tiers 1–3 here are DONE (shipped & merged to `main`, HEAD `c0e46f6`); only Tier 4 remains and is expanded in **`HANDOFF-TIER4.md`** (one level up). Kept as the record of the Tier 1–3 backlog and what shipped.

# Handoff — what's left to design (persFin)

> Forward-looking companion to `HANDOFF-PHASE4-ROLLOUT.md` (which covered the
> "alive" rollout, now complete). This doc is the **next-design backlog**: what
> still needs design/build, in priority order, with the reusable pieces and the
> guardrails. Read `HANDOFF-PHASE4-ROLLOUT.md` §1–§4 first for repo layout, the
> verification harness, and the locked design decisions — they still apply.

**Date:** 2026-06-17. **Branch:** `feature/frontend-elevation` (all work committed,
**not pushed**). **App root:** `Personal-FinanceAPP/`. Run from there: `npx tsc -b`
(keep at 0), `npx vitest run` (keep green — 41 files / 214 tests), `npm run dev`
(must be **:5173** — see harness note in the rollout handoff §4).

---

## 0. Where we are (done)

- **"Alive" rollout COMPLETE** for every real finance page: Overview, Accounts,
  Transactions, Budgets, Goals, Forecast, Subscriptions, Reconcile, Tax. Verified
  light + dark.
- **Overview hero**: the Safe-to-Spend gauge is the first pane (wide 2-col); the
  flat duplicate retired; tab-title preserved.
- **Navigation shipped**: a collapsible **left rail** (`SidebarRail`, grouped
  Ledger/Tools/Game, folio numbers, hover-expand) + a **⌘K "Jump to" palette**
  (`NavPalette`) in the header. The old top-tabs are gone. Mobile = hamburger →
  Sheet → Sidebar (unchanged).
- **Game-mode atmosphere fixed**: the heavy WebGL phosphor field (`GuillocheGL`)
  is now **full-only**; ambient gets just the light canvas breather + cursor glow,
  so ambient is legible and ambient→full is a clear step.
- **Full-mode graceful fallback**: the home falls back to Overview when there's no
  game data (so full mode never lands on a blank Expedition). `nav.tax` label and
  Link Bank visibility fixed.

**Reusable primitives already built (REUSE these, don't reinvent):** `TiltCard` /
`Card raking` (`components/ui/card.tsx`), `Certificate` with `alive`
(`components/engraving/Certificate.tsx`), `Reveal`/`RevealItem`
(`components/motion/Reveal.tsx`), `SidebarRail`, `NavPalette`, `AnimatedNumber`,
`Figure`, `Stamp`, `Guilloche`/`GuillocheBand`/`CornerRosette`, `Sparkline`,
`SectionRule`, the Atlas layers, `useReducedMotion`/`usePointerFine`. Nav data +
grouping: `components/layout/nav.ts` (`NAV_ITEMS`, `group`, `NAV_GROUPS`).

---

## 1. NON-NEGOTIABLE guardrails (carry forward)

- **Palette LOCKED**: Ledger Paper (light) / Midnight (dark). Don't change tokens.
- **Color law**: money figures stay sober (`.figure`/`.ledger-figures`, filter:none);
  green = money in, red = money out; **amber = the game layer only**; **red = bosses
  ONLY** (never a user number). This matters most in the game layer below.
- **No new dependencies** — the engraving/motion/atlas toolkit covers it.
- **Mode discipline**: components read `useFlags()`/`useTerm()`, never branch on
  `mode` directly (a grep test enforces it).
- **Per page**: elevate as a real design exercise (vary motion, don't reflex the
  same hover everywhere); verify live in the harness light + dark; keep tsc 0 /
  tests green; commit per surface. See `feedback-elevate-rollout-per-page` memory.

---

## 2. The design backlog (priority order)

### TIER 1 — finish the finance surfaces (small, high value) — ✅ DONE (2026-06-17)
- [x] **Settings page** (`pages/Settings/Settings.tsx`) — elevated. Form cards →
      `Card raking` (no tilt under inputs); Reveal stagger per tab; SectionRule
      rhythm (Thresholds/Atmosphere/Assistant); Accounts list → alive ledger-rows
      with manicule. (commit `51b79d4`). Automation/Memory/Agent-Keys tabs were
      already rich `.plate` designs — left as-is, just wrapped in Reveal.
- [x] **Empty states & first-run / onboarding** — new reusable
      `components/engraving/EmptyState.tsx` (heavy plate + hairline gold inner
      frame, breathing guilloché, motif, eyebrow/title/desc + CTA, Reveal entrance,
      reduced-motion safe). Wired into Accounts (→New Account), Budgets (→Rule a
      budget), Goals (→Chart a goal), Subscriptions, Forecast ("Here be dragons").
      Transactions empty got a warmer inline treatment (stays inside its ledger
      card). (commit `2ced414`). REUSE `EmptyState` for any future no-data surface.
- [x] **Mobile pass** — shared `TabsList` now scrolls horizontally instead of
      clipping (Settings' six tabs were cut off at 375px); full ruled baseline.
      Header hamburger → 44px tap target. Verified Overview/Transactions/Settings
      at 390px. (commit `6b08ef0`). NOTE: the AppShell header/sidebar can't be seen
      in the DevPreview harness (no auth) — only the hamburger size was changed
      (lg:hidden, desktop untouched); a fuller shell-mobile review still warranted.

### TIER 2 — public / pre-login (medium) — ✅ DONE (2026-06-17)
- [x] **Landing / marketing page** — `pages/Landing/Landing.tsx`, a React port of
      `landing.html` on the Ledger system (sticky shrinking register, hero +
      animated specimen note, proof, 6 instrument plates, how-it-works rows, struck
      coin, CTA, colophon; scroll-reveals via motion whileInView, reduced-motion
      safe). Public route `/welcome`; **ProtectedRoute now redirects signed-out
      visitors to `/welcome`** (landing carries the sign-in/open-account CTAs);
      `/login` still directly reachable. (commit `05d89cf`).
- [x] **Login page** — matched to the landing: "← The Ledger" back-link, "good
      standing" tagline, breathing centre guilloché, assurances strip. Form stays a
      static plate. (commit `68fbeeb`).

### TIER 3 — the game layer (LARGE; deferred; needs backend data)
> Gated behind game mode (ambient/full). The `/game/*` endpoints must serve data
> for any of these to render — today they're empty, so the pages show empty/
> placeholder states (and full-mode home falls back to Overview). This is the
> single biggest remaining design+build. Confirm scope with the user before
> starting. Color law is HEAVIEST here (amber = game, **red = bosses only**).
- [ ] **Expedition map** (`pages/Expedition/Expedition.tsx`) — "month as a 3-act run"
      as a flavored map with seeded creatures (full) / plain calendar (off/ambient).
      Prototype: `design-prototypes/page-game-home.html`.
- [ ] **Keeper** ("The Keeper" / Profile & Progress) — level/XP, the four stats,
      calibrating state.
- [ ] **Debts** ("Boss Battles") — boss liabilities + bestiary/monsters. Red = bosses.
- [ ] **Campaigns** ("The Campaign" / Quarterly Review) — campaign + challenges.
- [ ] **Goals "Cabinet"** — the game collectibles surface for Goals (minted coins,
      cabinet, bestiary). Prototype: `design-prototypes/page-goals-cabinet.html`.
- [ ] Decide game-nav visibility: in full mode the rail lists the game pages even
      with no data (they show empty states). Option to hide them until the game
      backend serves data (open question raised with the user).

### TIER 4 — richer interactions (optional / ambitious)
- [ ] **Command Deck** — we shipped a *nav-only* ⌘K palette. The fuller vision is a
      command deck that also runs **actions** (add transaction, link bank, jump to a
      scenario) — a reskin of the existing `AssistantInterface`. Prototype:
      `design-prototypes/page-command-deck.html`. See `persfin-frontend-elevation-direction`.
- [ ] **AssistantInterface / Chronicler** — the AI chat surface (Sheet + voice +
      propose→confirm BridgeCard). Design polish + the Command-Deck integration above.
- [ ] **Notifications** (`NotificationBell`) — surface + center design.
- [ ] **Cashflow Timeline** (Overview) — works as designed (income up / bills down on
      a signed axis) but reads oddly with sparse data; consider plotting positive
      magnitudes or enriching the forward income/bill series.

---

## 3. Designed-but-not-wired prototypes (in `design-prototypes/`)
Each is an HTML prototype already built + chrome-verified; wire into React when its
tier comes up: `landing.html` (Tier 2), `page-ledger-empty.html` (Tier 1 empty
states), `page-command-deck.html` (Tier 4), `page-game-home.html` +
`page-goals-cabinet.html` (Tier 3). Atmosphere/language refs: `DESIGN-LANGUAGE.md`,
`core-ambient.html`, `dynamic.html`, `living-guilloche.html`.

---

## 4. Pre-merge hygiene (NOT design — do before merging, when the user says ready)
- [ ] **Remove the throwaway DEV-ONLY routes/pages** (handoff §8): `/atlas-preview`,
      `/directions`, `/living`, `/workspace`, `/dev-preview`, `/dev-nav` (in
      `main.tsx`) + their page dirs, **and** the `/tax/*` API mock + seed helpers in
      `DevPreview.tsx`. Must leave tsc 0 / tests green. Grep: `DEV-ONLY` in `main.tsx`.
- [ ] **Push** — nothing is pushed yet; the branch has no upstream. Push only when asked.

---

## 5. Pointers
- Locked decisions, harness, port-5173 gotcha, commit cadence: `HANDOFF-PHASE4-ROLLOUT.md`.
- Aesthetic system: `DESIGN-LANGUAGE.md` + the `persfin-design-system` / `persfin-design-prototypes` memories.
- Project memory worth reading first: `persfin-frontend-rollout-budgets` (rollout +
  nav + atmosphere state), `feedback-elevate-rollout-per-page`,
  `persfin-frontend-elevation-direction`, `persfin-landing-page`, `persfin-design-system`.
