> **⚠️ ARCHIVED — 2026-06-17, historical.** This phase shipped (the React app is built); kept for the record. Current forward doc: **`HANDOFF-TIER4.md`** (one level up).

# Phase 3 — React Implementation Plan ("Cartographer's Desk" → the real app)

> The surface-by-surface plan to port the approved design language into the live React app.
> Source of truth for *what to build*: `DESIGN-LANGUAGE.md`. This doc is *how to build it in
> React*. **Planning only — no app files are touched until this plan is approved.**
>
> Verified against real code (2026-06-15): React 18 + Vite + TS + Tailwind + Zustand +
> recharts + Radix; `<BrowserRouter><Routes>` in `main.tsx`; one big `StoreState` in
> `store/store.ts`; mode system in `store/gameMode.tsx`; `AppShell` = `<div><Header/><main>
> <Outlet/></main></div>`; `index.css` uses `@layer base/components/utilities` (+ reduce-motion
> at ~L391); 8 `components/engraving/*` exist; `BridgeCard.tsx` exists; `mulberry32` in
> `Guilloche.tsx`; NO Challenges page; none of motion/lenis/d3/ogl installed.

---

## 0.5 FIT AUDIT — does the NEW design actually drop into the EXISTING code? (added 2026-06-15)

> The first draft verified the app's *plumbing* but ASSUMED the new prototypes fit the existing
> files. This audit reads the real target files and classifies each claim. **Conflicts are
> flagged, not silently resolved** (per user). This corrects two mis-framed steps below.

**✅ VERIFIED clean fit:**
- **SeaChart → Forecast** (`pages/Forecast/Forecast.tsx`): the bespoke chart is a drop-in
  replacement for the `<Card>"Running Balance"</Card>` `AreaChart` in the *Projection* tab.
  `timeline` / `forecast` (incl. `trough_band`, `overdraft_probability`, `lowest_*`) are already
  in scope; uses the same `ink()` tokens; scenario state (`activeScenarioResult`) already in store.
  Step D is accurate.
- **Mode flags** (`store/gameMode.tsx`): `ModeFlags` comment literally says "Later packages
  extend this shape"; `flagsFor()` is the single derive point. Planned extension fits exactly.
  Step A's flag work is accurate.
- **Global mount point** (`AppShell.tsx`): confirmed `<div><Header/><main><Outlet/></main>…</div>`
  — LivingGuilloche/BurinCursor/MoodWatermark/Lenis mount here. Step B is accurate.

**⚠️ CONFLICT 1 — the Command Deck is NOT net-new; it overlaps a working component.**
`AppShell` already mounts **`<AssistantInterface/>`** (+ `<ChroniclerDrawer/>`). `AssistantInterface.tsx`
is a `Sheet`-based chat that ALREADY HAS: voice input (`useVoiceInput`), `BridgeCard` +
`ConfirmCard` (propose→confirm), `AssistantProposal`/`AssistantBridge` types, inline
`AnimatedNumber`/`Sparkline` artifacts, and the `/assistant/` wiring. **So "Command Deck" = reskin +
restructure of AssistantInterface into a ⌘K command surface with a DiffPlate — NOT a from-scratch
build.** Step E below is REWRITTEN accordingly. *Decision needed (see §7): does ⌘K replace, wrap, or
sit alongside the existing Sheet assistant + the Chronicler drawer?*

**⚠️ CONFLICT 2 — game surfaces already EXIST and are wired; Step F is mostly RESKIN, not build.**
`pages/{Debts(154L),Expedition(101L),Goals(516L),Keeper(164L),Campaigns(183L)}` already call
`/game/` endpoints. So Expedition/Debts/Goals/Cabinet(Keeper)/Bestiary = restructure existing
pages to the new visual language, NOT greenfield. **Only Challenges is genuinely new** (no page —
confirmed). *Decision default (per user): flag each page's reshape-vs-adapt call as I hit it.*
Step F below is RE-FRAMED as reskin-first.

**⚠️ CONFLICT 3 — Goals is already 516 lines** (full CRUD + auto-fund rules + charts). The
"constellation + ignite + Cabinet" is a sizable ADDITION/restructure on a heavy existing page, not
a fresh build — higher effort + regression risk than the plan implied. Flag at build time.

**Net effect on the plan:** plumbing/Step A/B/D = accurate. Step C (craft baseline on existing
pages) = accurate but bigger than implied (pages built for the old look). Step E = reframe to
"evolve AssistantInterface." Step F = reframe to "reskin existing game pages + build only
Challenges." Effort shifts from "build new" toward "refactor existing without regressing" — which
is *more* delicate, not less. Build order unchanged.

---

## 0. Context — why & guardrails

The backend (~110 endpoints) far outstrips today's UI. We're adding a **mode-gated** spatial/
agentic layer ("Atlas canvas + Command Deck overlay") on top of the shipped Engraver's Ledger.
Because prototype tokens already MATCH `index.css`, this is **additive, not a rewrite**.

**Inviolable (carried from DESIGN-LANGUAGE.md §0):** color law (money never game-styled;
amber=game, red=boss-only) · mode discipline (`useFlags`/`useTerm`, never `if(mode===…)`;
`off` pixel-honest) · engine authority + propose→confirm + no real-money movement · a11y +
reduce-motion fallback for every effect.

**Working agreement:** feature branch (never default/`main`); each surface gated by mode;
verify each step with chrome-devtools (now permission-allowed) across off/ambient/full ×
light/dark × motion/reduce-motion; keep `vitest` + `./.venv/bin/pytest -q` green.

---

## 1. Dependencies to add (`Personal-FinanceAPP/package.json`)

| Pkg | Why | Load |
|---|---|---|
| `motion` (Framer) | spring tilt, deck transitions, stagger, layout | normal import |
| `lenis` | smooth scroll for scroll-reveals | normal, mount once in AppShell |
| `d3-scale` + `d3-shape` | SeaChart axes + path/area generation | imported only by `SeaChart.tsx` |
| `ogl` (~12kb) | full-mode living-guilloché shader + optional WebGL coin | **lazy** `import()` only |

Reject: Three.js, GSAP, particle libs. After install: `npm i`, confirm `tsc -b` + `vite build`
clean, app still boots. Commit deps as their own step so a bad dep is easy to bisect.

---

## 2. Build order (dependency-first; each is shippable + verifiable on its own)

> Rationale: build the shared **primitives** before any surface that needs them, broad-low-risk
> **craft baseline** before bespoke heroes, then heroes, then game, then the long tail. Each
> step ends green + chrome-devtools-screenshot-verified.

### STEP A — Foundation: tokens, easing, focus ring, a11y primitives (no visual risk)
The cheap, global, correctness-first layer everything else depends on.
- **`index.css` additions** (into existing `@layer` blocks): the NEW motion tokens
  (`--ease-out: cubic-bezier(0.22,1,0.36,1)` ← shipped value; `--ease-in-out`, `--ease-stamp`),
  the formal **z-index scale** vars, the **outline focus ring** (`:focus-visible{outline:2px
  solid hsl(var(--gold));offset:2px}` + `.opt/.row` inset variant), the **hover-gate** wrap
  (`@media (hover:hover) and (pointer:fine)`) around existing `.plate/.btn/.row` hovers, and
  the **raking-light** `.plate::after`. Apply the **reconciliations** (DESIGN-LANGUAGE §6):
  dark `--debit` +3–4%, `--boss-accent` stays shipped `0 72% 51%`.
- **`components/a11y/FocusRing` is just CSS** (above) — no component needed; but add a
  `useReducedMotion()` hook (or reuse Motion's) + a `usePointerFine()` hook for JS gates.
- **Extend `ModeFlags`** in `store/gameMode.tsx` for the new surfaces (e.g. `atlas`,
  `commandDeck`, `cabinet`, `bestiary`, `livingGuilloche`, `burin`) — all derived from `mode`,
  preserving the no-branch-on-mode invariant. `commandDeck`+SeaChart are finance tools → on in
  `off` too; game surfaces → ambient+.
- **Verify:** keyboard-tab the app, focus ring visible everywhere; touch emulation shows no
  false hover; contrast still ≥AA; nothing else changed. Tests green.

### STEP B — Global ambient layers (mount once in AppShell)
- **`components/atlas/LivingGuilloche.tsx`** — Canvas/SVG breathing rosette, FIXED center,
  data-seeded (`mulberry32` from net worth/month; reuse `Guilloche.tsx`'s PRNG). `off`=frozen
  static; `ambient`=drift; `full`=lazy-`import('ogl')` cursor-warp + phosphor with try/catch →
  static-SVG fallback. DPR-capped, **pause when tab hidden / offscreen**, reduce-motion=static.
- **`components/atlas/BurinCursor.tsx`** — nib + `#ink` fading-gold-trail canvas; burin↔manicule
  morph over interactive els; gates: ambient/full && pointer:fine && !reduce-motion; native
  caret over inputs. Single global instance.
- **`components/atlas/MoodWatermark.tsx`** — faint solvency figure (sun/storm) from `/forecast/`
  state; time-of-day warming = full only; always behind figures, `aria-hidden`.
- Mount these in `AppShell.tsx` as siblings before `<Header/>`/`<main>`; mount **Lenis** here too.
- **Verify:** mode dial off/ambient/full each correct; reduce-motion kills burin+motion; `off`
  ships ~0 extra weight (OGL never loaded); Lighthouse perf sane.

### STEP C — Craft baseline across existing pages (broad, low risk, high lift)
Apply the shared upgrades to the pages that already exist (no new routes yet):
- **Parallax tilt** on `.plate` (Motion `useSpring`, stiffness~100 damping~10 — NOT raw
  pointermove), money-change gold shimmer on `AnimatedNumber`, manicule rows + `:focus-visible`
  reveal, scroll-reveal (Lenis + `IntersectionObserver`), `GuillocheBand` dividers, meaningful
  microprint + deterministic serials on "documents".
- **Re-skin recharts** to steel-engraving (hatch fills, hairline axes, serif numeric labels) via
  `lib/chart.ts` — lifts every existing chart at once.
- **Showpiece empty states** (`components/empty/*`): Certificate "AWAITING FIRST ENTRY",
  uncharted "HERE BE DRAGONS" sea, empty constellation, "NO OUTSTANDING OBLIGATIONS" reward
  seal — wired into the real empty conditions on Accounts/Forecast/Goals/Transactions/Debts.
- **Verify:** each existing page in 3 modes × 2 themes; money figures still sober (`.figure`
  guard intact); tests green.

### STEP D — Hero: Forecast Sea-Chart (the centerpiece vertical slice)
- **`components/custom/Forecast/SeaChart.tsx`** — bespoke SVG + `d3-scale`/`d3-shape`. Inputs:
  `/forecast/` (`timeline`, `trough_band`, `overdraft_probability`, `lowest_*`). Render:
  coastline (`draw-x` self-ink), CI depth-bands (3 washes of `--chart-3`), shoal zero-line
  (`--debit` dashed), wax **sounding** seal = overdraft %. **Drag the coastline 1:1** (grab
  nearest pt, feather ±3) → debounce → `/scenarios/evaluate/` (store already has
  `activeScenarioResult`) → re-ink. Reduce-motion renders final immediately; **plain recharts
  fallback** for `off`/a11y/no-JS.
- Swap it into `pages/Forecast/Forecast.tsx`'s "Projection" tab (keep the existing scenario
  builder/compare tabs). Keep `PromissoryPlate` figures sober.
- **Verify:** depth band == `trough_band`; sounding == `overdraft_probability`; drag matches
  `/scenarios/evaluate/`; keyboard + SR read the literal numbers; reduce-motion path; screenshot.

### STEP E — Command Deck (EVOLVE the existing AssistantInterface, per Conflict 1)
NOT greenfield. `AssistantInterface.tsx` already does chat + voice + BridgeCard/ConfirmCard +
inline artifacts + `/assistant/` wiring. The work is to **restructure it into a ⌘K command
surface** and **upgrade BridgeCard → DiffPlate**:
- Add a `useCommandDeck` (⌘K open/close, focus trap + restore, combobox/listbox/option a11y,
  `aria-live` reply, page-recede). Decide its relationship to the current `Sheet` + the
  `ChroniclerDrawer` (§7 decision) — likely: ⌘K becomes the primary entry; the Sheet either
  becomes the deck's body or is retired.
- **Upgrade (not replace) `BridgeCard.tsx`** into the DiffPlate look (before/after engine state,
  red-strike removals / green adds, Authorize→APPROVED `stamp-in`) — keep its working
  propose→confirm→verify logic and tests.
- Reuse existing wiring: `/assistant/chat/`, `/assistant/actions/propose|confirm/`,
  `/assisted-actions/`, `useVoiceInput`(`/assistant/transcribe/`). InlineArtifact = the existing
  inline `AnimatedNumber`/`Sparkline` pattern extended to a mini SeaChart / S2S certificate.
- Summon affordance in `Header.tsx`. Available in `off` (finance tool). **emil:** ⌘K is
  keyboard-opened → animate the plate, not the keystroke.
- **Verify:** existing assistant flows still work (don't regress voice/chat/bridge); ⌘K
  open/close/Esc, focus trap+restore, arrow-select, Enter commit, DiffPlate renders, Authorize
  stamps, propose→confirm→verify green; screenshot light/dark.

### STEP F — Game surfaces (RESKIN existing pages + build only Challenges, per Conflict 2/3)
These pages EXIST and are wired to `/game/`. Work = restructure to the new visual language WITHOUT
regressing current behavior. **Flag reshape-vs-adapt per page as I hit it** (user default).
Mode-gated; territory/CRT = full-only, plain fallbacks for ambient/off.
- **Expedition** (101L, exists) — reskin to voyage route + **render the ignored
  `/game/expedition/` modifiers** as a pre-month loadout (the one real feature gap here).
- **Debts** (154L, exists) — split into `Territory.tsx` (full, red boss-accent, VANQUISHED) +
  `Schedule.tsx` (plain, ambient/off) from `/game/bosses/`. Reshape, preserve data calls.
- **Bestiary** — animated-SVG specimens from `/game/monsters/` (Debts page already shows monsters;
  upgrade the rendering).
- **Challenges — the ONLY genuinely NEW page** (ZERO UI today) from `/game/challenges/`: add
  `pages/Challenges`, a `<Route gameOnly>` in `main.tsx`, a `nav.ts` entry (`gameOnly:true`).
- **Goals** (516L, exists — heavy: CRUD + auto-fund + charts) — ADD constellation star-chart +
  ignite-on-complete as a new view/mode on the page; do NOT break existing CRUD. Higher regression
  risk (Conflict 3) — treat carefully, lots of tests.
- **Cabinet + mint** — new surface (the missing trophy room), likely folded into `Keeper`(164L) or
  a new page: `Cabinet/{Grid,Coin,Seal}.tsx`, strike + faux-3D tilt (never `scale(0)`); aging wax
  `Seal` (extend `Seal.tsx`, `age`=streak).
- **Verify:** existing game-page behavior intact (don't regress); color law (only bosses red);
  ambient fallbacks; full extras; Challenges reachable; tests green.

### STEP G — Polish & QA pass (DESIGN-LANGUAGE §7 matrix)
will-change lifecycle (set on interaction, remove after), cap concurrent token-blur, optional
letterpress sound (off by default, Settings toggle), final reduce-motion + a11y sweep, Lighthouse,
full screenshot matrix.

---

## 3. Cross-cutting React decisions
- **Mode gating:** extend `ModeFlags`; components read `useFlags()`/`useTerm()` only. One grep
  test already enforces no `mode===`; keep it passing.
- **Motion:** prefer CSS transitions/keyframes for predetermined animation (off main thread,
  interruptible); Motion `useSpring`/layout for gesture/drag/shared-element. Use the full
  `transform:"translateX()"` string (not Framer `x`/`y` shorthand) where hardware-accel matters.
- **WebGL:** only via `await import('ogl')` inside a full-mode effect; try/catch → static
  fallback; pause on `document.hidden` + IntersectionObserver; cap DPR.
- **Perf:** transform/opacity only; virtualize long ledgers; debounce the SeaChart drag→evaluate.
- **State:** add to `StoreState` only what's shared (command-deck open state can be local; active
  scenario already in store). Don't bloat the store.

## 4. Risks & mitigations
| Risk | Mitigation |
|---|---|
| SeaChart bespoke render is the hard part | isolated component + recharts fallback; build as Step D slice, not big-bang |
| Density overwhelms casual users | game/cockpit gated to ambient+/full; `off` stays calm; progressive disclosure via ⌘K |
| Metaphor obscures the number | color law + always-literal `.figure` + plain-view toggle |
| WebGL jank/weight | lazy + paused + DPR-capped + reduce-motion off; `off` never loads it |
| Mode/color-law regressions | keep grep test; add a test asserting game-accent classes never hit `.figure`; screenshot audit |
| Burin hurts usability | ambient/full-only + reduce-motion/touch off + native caret + a user setting to disable |

## 5. Verification (per step + final)
- Per step: `vitest` + `./.venv/bin/pytest -q` green; chrome-devtools screenshot the touched
  surface in the relevant modes/themes.
- Final matrix: every surface × {off,ambient,full} × {light,dark} × {motion,reduce-motion}.
  Color-law audit (no money figure game-styled; bosses only red). Live contrast ≥AA. Lighthouse
  (confirm `off` ~0 extra weight, WebGL lazy/paused). Keyboard reach for ⌘K + every plate; SR
  reads literal numbers.

## 6. Suggested commit/PR sequence (on a feature branch)
1. deps · 2. Step A foundation · 3. Step B global layers · 4. Step C craft baseline · 5. Step D
SeaChart · 6. Step E Command Deck · 7. Step F game surfaces (sub-commit per surface) · 8. Step G
polish. Each commit independently green. PR per step or per logical group; never commit to default.

## 7. Open decisions to confirm before/at build start
- First step to actually BUILD (recommend A→B→C as one foundation push, then D as first hero).
- Burin cursor on in `ambient` or `full`-only? (a11y lean: setting-controlled, ambient default on.)
- How loud bestiary/sound/CRT in `full`.
- Whether `ambient` becomes the recommended post-opt-in landing (vs `full`).
