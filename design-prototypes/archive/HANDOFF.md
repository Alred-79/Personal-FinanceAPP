> **⚠️ SUPERSEDED — 2026-06-17.** Tiers 1–3 of the elevation shipped & merged to `main` (HEAD `c0e46f6`); the remaining work lives in **`HANDOFF-TIER4.md`** (one level up). Kept as a historical record of the original vision + roadmap.

# persFin Frontend Elevation — Master Handoff

> **Purpose:** Feed this file to a new chat to resume the persFin frontend/UX overhaul
> with zero context loss. It captures the vision, every decision, the current state, and a
> full roadmap from "finish the dynamic prototype" through shipping in the real React app.
>
> **Last updated:** 2026-06-14. **Status:** Prototyping phase. Baseline approved; extending
> to other pages next.

---

## 0. How to resume (do this first in the new chat)

1. Read the project memory's `persfin-frontend-elevation-direction` note first (it holds the
   NEXT-SESSION PLAN). Don't re-derive scope from generic specs.
2. Confirm tooling: run `claude mcp list`. **chrome-devtools** should be `✓ Connected` AND its
   tools (`take_screenshot`, `navigate_page`, `new_page`, etc.) should be callable — if you
   just restarted Claude Code, they will be. Use them to SEE every prototype, not just
   `node --check`. **Refero is intentionally SKIPPED** (don't use it).
3. Open `design-prototypes/dynamic.html` — this is the **approved interaction baseline**.
   Everything new extends it.
4. Pick up at **Section 4 (Roadmap) → Phase 1**, building the four remaining page prototypes.

**One-line kickoff for the user to paste:** *"Continue building the persFin page prototypes
per design-prototypes/HANDOFF.md — start with the Command Deck."*

---

## 1. The vision (what we're building)

**"The Cartographer's Desk."** Elevate persFin's frontend so it fully leverages a backend
that's far richer than the current UI exposes (~110 endpoints / 27 routers). Two combined
directions:
- **Atlas (spatial canvas)** = what you SEE. Money over time is *terrain*: the forecast is an
  engraved **sea-chart**, debts are territories, goals are a star-chart.
- **Command Deck (control overlay)** = how you ACT. A `⌘K` palette summons the agent, which
  compiles natural language into **propose→confirm diff plates** you authorize with a stamp.

Built on a deepened version of the existing **"Engraver's Ledger"** design system, made
**dynamic and interactive** (the big ask: not static, modern graphics, hover/cursor effects,
non-static components) — while staying **one cohesive, easily-ingestible product**.

---

## 2. The locked decisions (do not relitigate without the user)

### 2a. Governing principle (resolves "is this too much?")
**ONE metaphor: "engraved paper instruments."** Banknote + map + certificate are one family
of 19th-century engraved documents. **Anything that breaks "this is issued paper" gets
demoted to full-mode-only or cut.** This is the test for every new element.

### 2b. Mode discipline (the boldness dial)
The app already has `mode ∈ {off, ambient, full}` driving design tokens (`<html data-mode>`),
a copy term-catalog (`useTerm`/`<Term/>`), and feature flags (`useFlags`). **No component
branches on `mode` directly** — a grep test enforces this; gate via `flags`/`useTerm`.
- **`off`** = default; pixel-honest pure finance. NO game chrome, NO CRT, burin cursor OFF.
  (It still gets the calm craft baseline + the sea-chart + Command Deck — those are finance
  tools, not game.)
- **`ambient`** = the approved dynamic baseline (see `dynamic.html`): restrained-but-alive.
  Prominent, fun, but calm. This is where most users live once they opt in.
- **`full`** = bold & cinematic: CRT phosphor, animated creatures, WebGL coins, page-turns,
  sound, living-guilloché cursor-warp. Earned by opting in; never the default.

### 2c. Color law (sacred — enforced by the `.figure`/`.ledger-figures` CSS guard)
- **green/ink = real money truth.** Money figures NEVER get glow, CRT, WebGL, or game chrome
  (`filter:none !important; text-shadow:none !important`). They may only count-up.
- **amber = the game layer.**
- **red = bosses ONLY**, never a user's number.

### 2d. Inclusion bar
Every effect must **carry real meaning** (encode data or state). A few purely-delightful
exceptions are allowed if on-theme and rare (e.g. the minting flourish).

### 2e. Other hard constraints (from the product's governing docs)
- **Deterministic engine = authority; the LLM narrates/plumbs, never advises.** Every number
  is engine-recomputed; every action goes propose→confirm.
- **No real-money movement** (Plaid is read-only; the Bridge guides, the human pulls the
  trigger in their own bank).
- **Anti-dark-pattern:** no engagement-maxxing, no guilt, no streak punishment for engaged
  users; lapsed-user re-entry is gentle.
- **Accessibility:** every animation needs a `prefers-reduced-motion` static fallback. The
  burin cursor must be optional (ambient/full only), respect reduce-motion, and return the
  native caret over text inputs — never forced.

### 2f. Tech envelope (deliberate, scoped expansion)
The app currently has ONLY `recharts` + `tailwindcss-animate` (all existing craft is
hand-built CSS/SVG). Approved additions for the elevation:
- **Motion (Framer Motion)** — everyday React animation layer, everywhere.
- **Lenis** — smooth scroll (~3kb).
- **d3-scale + d3-shape** — for the SeaChart only (recharts can't do depth-contour CI bands).
- **OGL (~12kb, lazy-loaded behind dynamic import)** — selective WebGL for hero moments only
  (living-guilloché shader, full-mode metallic coin). $0 on first paint / `off` mode.
- **Reject:** Three.js (too heavy), GSAP (Motion covers it), particle libs (hand-roll on Canvas).
- Performance: WebGL lazy-loads + pauses offscreen + disabled by reduce-motion; transforms/
  opacity only for 60fps; everything has a no-JS/no-WebGL SVG fallback.

### 2g. Effect tiering (how many effects stay cohesive)
**One screen = one Tier-1 signature + at most one Tier-2 + ambient Tier-3.** Never two
signatures on one screen.
- **Tier 1 (signatures, own a surface, WebGL-eligible):** Sea-Chart self-inks (Forecast),
  Living guilloché (global bg), Territory reclaim (Debts, full-only), Constellation/star-chart
  (Goals), Mint a specimen (completions/Cabinet).
- **Tier 2 (interaction signatures, Motion, no WebGL):** Command Deck summon (⌘K),
  Page-turn navigation.
- **Tier 3 (ambient texture, always on, cheap):** raking-light/burin cursor, parallax tilt,
  manicule rows, money shimmer, scroll-reveals.

### 2h. "Soul" details (all approved)
- **Meaningful microprint + deterministic serials** — anti-counterfeit text encodes real
  data/mottos; each "document" gets a serial (`No. AB-04821`) seeded from its data.
- **Aging wax seal** — `Seal` gains ornamentation/patina as a streak grows (felt progression).
- **Mood watermark + time-of-day ink** — faint background figure reflects solvency (sun/storm);
  paper warms in the evening (time-of-day is full-only). Always behind figures.
- **Optional letterpress sound** — thunk on confirm, pen-scratch on entry, coin-ring on mint.
  OFF by default, single Settings toggle. (Full-mode affordance.)
- **Data-seeded guilloché SHAPE** — the rosette is generated from the user's net worth/month
  via the existing `mulberry32` PRNG, so each person's banknote is uniquely theirs.
- **Showpiece empty states** — blank certificate "AWAITING FIRST ENTRY", uncharted "HERE BE
  DRAGONS" sea, empty constellation, "NO OUTSTANDING OBLIGATIONS" reward-seal.

### 2i. Specific reframes (to keep coherence)
- **Debts** territory/boss/RPG metaphor = **full-mode-only**. ambient/off show a plain
  engraved debt schedule.
- **Goals** = engraved **star-CHART (a document)** in ambient; live particle starfield is
  full-only.
- **Ink-in-water shader creatures = CUT.** Creatures are **animated SVG line-art**
  (breathe/blink/drift), engraved sea-monster "specimens"; static in ambient, livelier in full.

### 2j. Cursor + sea-chart (from the latest prototype feedback)
- **Cursor = engraver's burin** leaving a fading gold ink trail (NOT a light/glow). System
  cursor hidden via `cursor:none` (native on touch). Accessibility caveats in 2e.
- **Background guilloché breathes but does NOT follow the cursor** (user: the logo/bg
  shouldn't move with the mouse).
- **Sea-chart what-if = drag the coastline itself, 1:1** (drag a point down = less money
  there; neighbors feather smooth). The old "drag-a-buoy-up-makes-it-dip-down" was confusing
  and is removed. Gold node dots signal grabbable; a Reset button restores baseline.
- **Kept:** 3D parallax plate tilt, coin strike + 3D tilt.

---

## 3. Current state (what exists right now)

### Prototypes (in `design-prototypes/`, self-contained HTML, faithful to real tokens):
- **`core-ambient.html`** — first restrained Bucket-A demo. Reaction: "cool but too static."
  Superseded; keep for reference.
- **`dynamic.html` — THE APPROVED BASELINE.** Contains: living guilloché (breathing, fixed
  center), engraver's-burin cursor + ink trail, 3D parallax plate tilt, drag-the-coastline
  sea-chart with live overdraft sounding, coin strike/3D-tilt mint, magnetic buttons, scroll
  reveals, accrual ticker, light/dark toggle. JS syntax-checks clean.

### Plans / specs (in `~/.claude/plans/`):
- **`the-full-power-of-serene-ember.md`** — the implementation-shape plan (Atlas + Command
  Deck, per-surface backend traceability, key files, verification).
- **`persfin-motion-and-graphics-language.md`** — the artistic/motion spec (tiers, per-surface
  assignments, tech envelope, soul details, resolved taste calls).

### Tooling:
- **chrome-devtools MCP** — installed (project scope, `--isolated`). Tools load after a Claude
  Code restart. Use to screenshot/inspect/verify every prototype.
- **Refero MCP** — installed + authed, but **user chose to SKIP it.** Do not use.
- **Skills available/relevant:** `frontend-design`, `ui-ux-pro-max` (+ companions),
  `impeccable`, `emil-design-eng` (apply its polish philosophy when building).

### The real app (where this eventually lands — NOT touched yet):
- Frontend: **Vite + React 18 + TS + Tailwind + Zustand + recharts + Radix**, root at
  `Personal-FinanceAPP/` (package.json + vite.config.ts there; source under `client/src/...`
  — note: NO package.json under `client/`).
- Backend: **FastAPI + SQLAlchemy/SQLite**, ~110 endpoints, at `Personal-FinanceAPP/server`.
- Design system lives in `client/src/index.css` (the Engraver's Ledger tokens, classes,
  motion vocabulary) + `client/src/components/engraving/` (Guilloche, Seal, Stamp, Certificate,
  AnimatedNumber, SectionRule, Figure, Sparkline).
- Mode system: `client/src/store/gameMode.tsx`. Nav: `client/src/components/layout/nav.ts`.
- Key reuse seams: `Forecast.tsx` already returns `trough_band` + `overdraft_probability`;
  `BridgeCard.tsx` already does propose→confirm→verify (generalize it for the diff plate).
- Tests: backend `./.venv/bin/pytest -q` from `Personal-FinanceAPP/`; frontend vitest.

---

## 4. ROADMAP (the rest of the plan, in order)

### ✅ Phase 0 — Direction & baseline (DONE)
Vision chosen, decisions locked, `dynamic.html` baseline approved.

### ▶ Phase 1 — Finish the page prototypes (NEXT; all four, extend `dynamic.html`)
Build each as a self-contained HTML in `design-prototypes/`, then **screenshot + inspect with
chrome-devtools** and verify the color law + reduce-motion hold. Order:
1. **Command Deck (`⌘K` overlay)** — palette over the page (page recedes/desaturates), agent
   reply inks in token-by-token, a **propose→confirm diff plate** (red-ink removals / green-ink
   additions) with an **Authorize stamp** (reuse the BridgeCard pattern). Tier-2, no WebGL.
2. **Game home + Debts/bestiary** — expedition voyage route; Debts as **full-mode territory/
   boss** (red boss-accent only here) with a plain engraved schedule fallback; **animated SVG
   creatures** (breathe/blink/drift). Tests the "gamified, fun, unique" ask.
3. **Goals constellation + Cabinet** — Goals as an **engraved star-chart** (ambient) /
   particle starfield (full); the **Cabinet** of minted coins/seals (the collectible
   progression surface the app currently lacks). Ignite-on-complete.
4. **Ledger + showpiece empty states** — elevated transactions ledger (manicule rows, shimmer,
   parallax) + the **first-run empty-state scenes** (blank certificate, uncharted sea, etc.).

Deliverable: 4 approved page prototypes + user sign-off on the look/feel of each.

### Phase 2 — Consolidate the prototypes into a design-language reference
Once all pages are approved, distill the prototypes into a **single component/effect reference**
(the canonical CSS keyframes, the burin/tilt/ink-trail JS, the SeaChart algorithm, the mint
animation) so the React port copies from one source of truth, not five HTML files. Update
`persfin-motion-and-graphics-language.md` with final values.

### Phase 3 — React implementation plan (turn art into a build plan)
Write the surface-by-surface implementation plan against the REAL app:
- Add deps (Motion, Lenis, d3-scale/shape, OGL) to `Personal-FinanceAPP/package.json`.
- New components: `SeaChart.tsx`, `CommandDeck/` (CommandBar, DiffPlate, InlineArtifact),
  `BurinCursor.tsx`, `LivingGuilloche.tsx` (lazy WebGL), `Cabinet/`, creature components.
- Generalize `BridgeCard.tsx` → diff plate. Extend `index.css` tokens + keyframes. Extend
  `ModeFlags` in `gameMode.tsx` for new game surfaces (keep no-branch-on-mode invariant).
- Map each surface to its backend endpoint(s) (traceability table is in
  `the-full-power-of-serene-ember.md`).
- Decide build order: recommend **Tier-3 craft baseline + chart re-skin first** (broad, low
  risk), then **one Tier-1 hero (Sea-Chart) vertical slice** as proof.

### Phase 4 — Build it, tier by tier, in the real app
1. **Craft baseline** across all screens (raking-light/burin, parallax, shimmer, scroll
   reveals, steel-engraving recharts skin, soul details). Lifts the whole app cheaply.
2. **Sea-Chart hero** (Forecast) — the bespoke SVG/d3 + drag-the-coastline + live re-ink
   against `/scenarios/evaluate/`.
3. **Command Deck** — ⌘K + diff plate (generalized BridgeCard) + inline artifacts.
4. **Game surfaces** — Expedition voyage, Debts (full-mode territory), creatures/bestiary,
   build the **Challenges** UI (currently ZERO frontend), render the ignored expedition
   **modifiers** as a pre-month loadout.
5. **Goals constellation + Cabinet**, showpiece empty states, aging seals, data-seeded
   guilloché wired to real net worth, optional sound.

Each step: gate by mode, honor color law + reduce-motion, screenshot-verify with
chrome-devtools across off/ambient/full, run vitest + pytest.

### Phase 5 — QA, polish, ship
- Visual QA matrix: every surface × {off, ambient, full} × {light, dark} × {motion,
  reduce-motion} via chrome-devtools screenshots.
- Color-law audit (no money figure gets game/WebGL chrome; bosses are the only red).
- Performance: Lighthouse via chrome-devtools; confirm WebGL is lazy + paused offscreen and
  `off` mode ships ~zero extra weight.
- Accessibility pass (keyboard reach for ⌘K and every plate; burin cursor optional; SR reads
  literal numbers).
- Commit on a feature branch (the repo uses feature branches; don't commit to default).

---

## 5. Open questions to confirm with the user (carry forward)
- After Phase 1, which surface to build FIRST in the real app (recommend: craft baseline, then
  Sea-Chart slice).
- Whether `ambient` should be the recommended landing after opting into the game (vs `full`).
- Exact intensity of creatures/sound/CRT in `full`.
- Whether the burin cursor stays on in `ambient` or is `full`-only (accessibility call).

---

## 6. Pointers
- Memory note: `persfin-frontend-elevation-direction` (has the live NEXT-SESSION PLAN).
- Design system memory: `persfin-design-system` (Engraver's Ledger primitives + tokens).
- Layout memory: `persfin-dual-tree-layout` (code lives in `Personal-FinanceAPP/`, NOT the
  project root; never run against the OneDrive tree's node_modules).
- Plans: `~/.claude/plans/the-full-power-of-serene-ember.md`,
  `~/.claude/plans/persfin-motion-and-graphics-language.md`.
- Prototypes: `design-prototypes/dynamic.html` (baseline), `core-ambient.html` (reference).
