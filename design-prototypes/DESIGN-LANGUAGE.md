# persFin Design Language — Single Source of Truth (Phase 2 consolidation)

> Distilled from the 5 prototypes (`dynamic.html` baseline + 4 page prototypes) + the
> review fixes (REVIEW.md) + the SHIPPED `index.css`. This is what the React port copies
> from — not the individual HTML files. Where a prototype and the shipped app differ, the
> **shipped app wins** (identity preservation).
>
> Canonical source files: `Personal-FinanceAPP/client/src/index.css` (tokens, classes,
> keyframes — already in production) and `client/src/components/engraving/*` (Guilloche,
> Seal, Stamp, Certificate, AnimatedNumber, SectionRule, Figure, Sparkline).
>
> **Key finding:** the prototypes add a *layer* on top of an already-coherent shipped
> system. Most tokens/keyframes ALREADY EXIST in index.css. Phase 2's job is to document
> the NEW pieces (burin, parallax, SeaChart, diff-plate, mint, focus ring, a11y) and the
> handful of reconciliations.

---

## 0. The four laws (non-negotiable, enforced)

1. **Color law** — green/ink = real money (`.figure`,`.ledger-figures` carry
   `filter:none!important; text-shadow:none!important`); **amber (`--game-accent`) = game
   layer**; **red (`--boss-accent`) = bosses ONLY**. Never decorate a money figure.
2. **Mode discipline** — `mode ∈ {off,ambient,full}` via `<html data-mode>`; gate with
   `useFlags()`/`useTerm()`, NEVER `if(mode===…)` (grep-test enforced). `off` = pixel-honest
   pure finance.
3. **Engine authority** — every number engine-recomputed; every action propose→confirm; LLM
   narrates, never advises. No real-money movement (read-only Plaid; human pulls trigger).
4. **Accessibility** — every animation has a `prefers-reduced-motion` fallback; burin cursor
   is ambient/full-only + off under reduce-motion/touch + native caret over inputs; visible
   focus ring on everything; data canvases get `role=img`+label, decorative ones `aria-hidden`.

---

## 1. Tokens (CANONICAL — all already in index.css unless marked NEW)

### Color (HSL channels; light "Ledger Paper" / dark "Midnight Vault")
| Token | Light | Dark | Use |
|---|---|---|---|
| `--background` | `44 42% 93%` | `168 30% 6.5%` | page |
| `--foreground` | `167 28% 14%` | `44 36% 87%` | text |
| `--card` | `46 52% 96.5%` | `167 26% 9.5%` | plate bg |
| `--muted-foreground` | `160 10% 37%` | `152 10% 56%` | labels (✓AA: 5.26 / 6.14) |
| `--primary` | `164 40% 22%` | `156 30% 64%` | buttons |
| `--gold` | `42 56% 44%` | `43 62% 56%` | accent/action chrome/seals |
| `--rule` | `152 10% 72%` | `164 12% 20%` | hairline |
| `--rule-strong` | `162 16% 38%` | `154 16% 48%` | plate edge |
| `--paper-high` | `48 60% 98%` | `166 22% 12%` | top-light inset |
| `--ink-wash` | `160 18% 90%` | `166 20% 12%` | hover wash |
| `--debit` | `8 62% 41%` | `8 64% 58%` | money out (✓AA: 6.03 / 4.67⚠) |
| `--credit` | `162 45% 26%` | `156 34% 56%` | money in (✓AA: 6.97 / 6.98) |
| `--chart-1…6` | (steel inks) | (lighter) | data viz; `--chart-3 215 32% 40%` = coastline |
| `--game-accent` | `38 92% 50%` | (same) | amber game layer ONLY |
| `--boss-accent` | `0 72% 51%` | `5 72% 58%`* | red bosses ONLY |
| `--crt-intensity` | `0`/`0.4`/`1` | per data-mode | CRT dial |

*Prototype game-home used `--boss: 5 68% 42% / 5 72% 58%`; reconcile to shipped
`--boss-accent: 0 72% 51%` for light. **RECONCILE in port.**

**Review nit (P3):** dark `--debit` is 4.67:1 — passes AA but tightest. **Nudge dark
`--debit` lightness +3–4%** (e.g. `8 64% 62%`) for headroom on small tabular figures.

### Geometry / type
- `--radius: 0rem` (sharp corners — no rounding, no blur, no gradients).
- Fonts: **Fraunces** (display/intaglio, `opsz` 80 headings / 144 `.intaglio`),
  **Instrument Sans** (body, `ss01` on), **Spline Sans Mono** (tabular figures).

### Motion tokens — **NEW (add to index.css `:root`)**
```css
--ease-out: cubic-bezier(0.22, 1, 0.36, 1);     /* SHIPPED value — reconcile prototypes'
                                                    .23,1,.32,1 to THIS */
--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);
--ease-stamp: cubic-bezier(0.34, 1.56, 0.64, 1); /* recoil — shipped stamp-in curve */
```
emil note: these are stronger than CSS built-ins (correct). Durations: press 100–160ms,
tooltip 125–200ms, dropdown 150–250ms, modal/deck 200–500ms; UI ≤300ms; exit ~60–70% of enter.

### Z-index scale — **NEW (formalize; prototypes used ad-hoc values)**
```css
--z-veil:40; --z-deck:50; --z-grain:9999; --z-ink:9000; --z-toolbar:10000; --z-nib:10001;
```
Real app needs a semantic scale: dropdown < sticky < modal-backdrop < modal < toast <
tooltip < cursor-layer. Map the above into it during the port.

---

## 2. CSS primitives (canonical)

### Already shipped (reuse as-is)
`.plate` (double-rule card + inset top-light), `.plate::before` (inner hairline),
`.microprint`, `.dept-label`, `.intaglio`, `.ledger-figures`/`.figure` (+ the color-law
`filter:none` guard), `.ledger-row` + `.manicule`, `.press`, `.section-rule`,
`.ink-debit`/`.ink-credit`, paper grain (`body::after` feTurbulence), engraved
`:focus-visible` (the shipped one — but see NEW focus ring below).

### Motion vocabulary — shipped keyframes (reuse)
`rise-in`, `ink-in`, `draw-x`, `rotate-slow`, `stamp-in`, `seal-pulse`, `count-up`,
`terminal-blink` + `.delay-1…6` stagger helpers + the `@media (prefers-reduced-motion)`
block. **All exist.**

### NEW primitives (from prototypes + review — add these)
```css
/* P0 focus ring — OUTLINE not box-shadow (box-shadow loses to .btn/.summon own shadows) */
:focus-visible{outline:2px solid hsl(var(--gold));outline-offset:2px}
.opt:focus-visible,.row:focus-visible{outline-offset:-2px}

/* Parallax plate: 3D tilt toward cursor (JS sets transform; spring it in React) */
.plate{transform-style:preserve-3d;transition:box-shadow .25s var(--ease-out),transform .12s var(--ease-out)}
.plate::before{transform:translateZ(20px)} .plate>*{transform:translateZ(30px)}

/* P2 hover-gate: hover-depth only on real hover (no false hover on touch) */
@media (hover:hover) and (pointer:fine){ .plate:hover{…} .btn:hover{…} .row:hover{…} .mod:hover{…} }
/* keyboard equivalent: .row:focus-visible .man{opacity:1;transform:none} */

/* Raking-light (ambient hover): radial highlight at --mx/--my (pointer-driven) */
.plate::after{background:radial-gradient(420px circle at var(--mx) var(--my),hsl(var(--paper-high)/.9),transparent 45%);opacity:0;transition:opacity .3s var(--ease-out)}
.plate:hover::after{opacity:.7}  /* dark: gold tint */

/* Burin cursor (ambient/full only) */
body{cursor:none} @media (pointer:coarse){body{cursor:auto}}
#cmd,input,textarea{cursor:auto}   /* native caret returns over text inputs */
/* nib burin↔manicule morph over interactive els; #ink canvas = fading gold trail */
@media (prefers-reduced-motion:reduce){ body{cursor:auto} #nib,#ink{display:none} … }
```

---

## 3. JS algorithms (canonical — pseudocode + where the real code is)

All deterministic, seeded by `mulberry32` (already in `Guilloche.tsx`). Money figures never
animated by these.

1. **Living guilloché** (`LivingGuilloche.tsx`, lazy WebGL/Canvas) — 9 rings, per-ring
   `{k1∈3..11, k2∈2..8, phase}`, **breathes** (`amp*(1+0.04·sin(t·1.3+r))`), **fixed
   center** (does NOT follow cursor — user decision). `off`=frozen static SVG;
   `ambient`=drift; `full`=+cursor-warp + phosphor. Pause offscreen; reduce-motion=static.

2. **Burin cursor + ink trail** (`BurinCursor.tsx`) — nib `<svg>` follows pointer; over
   `button,a,input,.opt,.mod,[role=button],label` it morphs burin→manicule + tints gold;
   `#ink` canvas draws gold hairline segments between pointer samples, faded each frame
   (`destination-out` 6% veil); click = small gold "bite". Gate: ambient/full, !touch,
   !reduce-motion.

3. **SeaChart** (`SeaChart.tsx`, SVG + `d3-scale`/`d3-shape`) — coastline = balance line;
   **CI depth-bands** = `trough_band` washed below in 3 concentric `--chart-3` layers;
   **shoal** = zero line (`--debit` dashed); **sounding** = wax seal printing
   `overdraft_probability`. **Drag the coastline 1:1** (grab nearest point, feather ±3
   neighbors with `w=max(0,1-|d|/4)`) → recompute → call `/scenarios/evaluate/`. Self-inks
   on load: coastline `draw-x` L→R, bands wash up, sounding stamps. Reduce-motion: render
   final state immediately. Has a recharts/plain fallback for `off`+a11y.

4. **Command Deck diff-plate** (`CommandDeck/`) — ⌘K opens; page recedes (scale .985 +
   veil; drop the `filter` animation or accept its cost); agent reply inks in token-by-token
   (`.tok{opacity:0;filter:blur(2px)}`→`.in`, ~50ms stagger, fixed base ~120ms); diff rows
   red-strikethrough removals / green additions; **Authorize → APPROVED stamp** (`stamp-in`).
   Generalizes the SHIPPED `BridgeCard.tsx` propose→confirm→verify. a11y: combobox/listbox/
   option roles, `aria-activedescendant`, focus trap + restore, `aria-live=polite` reply.

5. **Mint a specimen** (`Cabinet/Coin.tsx`) — strike keyframe scale `2→.92→1` + `rotateY
   180→0`, gold glint sweep; hover = faux-3D tilt (`preserve-3d`, ≤±32°). Never start from
   `scale(0)` (emil). Coins collect in the Cabinet. `full` may upgrade to WebGL metal.

6. **Aging wax seal** (extend `Seal.tsx`) — `age`(=streak weeks) drives size (44→~91px),
   milled teeth (20→52+), wax darkness, ornamentation ring width (`floor(age/12)`). Felt
   progression, no number.

7. **Data-seeded guilloché** — feed `mulberry32` a net-worth/month-derived seed so each
   user's banknote rosette is theirs. Stable fallback seed when logged-out/empty.

8. **Meaningful microprint + serial** — microprint encodes real data/motto; serial =
   `LL-NNNNN` deterministic from the document's data.

---

## 4. Component → React target → backend endpoint (port map)

| Prototype piece | React component (new unless noted) | Endpoint(s) | Mode |
|---|---|---|---|
| Forecast sea-chart | `SeaChart.tsx` (+plain fallback) | `/forecast/`, `/scenarios/evaluate/` | all |
| Command Deck | `CommandDeck/{Bar,DiffPlate,InlineArtifact}` ; generalize `BridgeCard.tsx` | `/assistant/chat/`, `/assistant/actions/propose|confirm/`, `/assisted-actions/`, `/assistant/transcribe/` | all (tool) |
| Expedition voyage | `Expedition/Voyage.tsx` (+loadout) | `/game/expedition/` (incl. ignored modifiers) | ambient+ |
| Debts territory / schedule | `Debts/Territory.tsx` (full) + `Schedule.tsx` (ambient/off) | `/game/bosses/` | territory=full only |
| Bestiary | `Bestiary/Specimen.tsx` (animated SVG) | `/game/monsters/` | ambient+ |
| **Challenges (ZERO UI today)** | `Challenges/` (new page) | `/game/challenges/` | ambient+ |
| Goals constellation | `Goals/StarChart.tsx` (+full starfield) | goals endpoints, `?goal=` deep-link | ambient+ |
| Cabinet + mint | `Cabinet/{Grid,Coin,Seal}.tsx` | game stats/streak/keeper | ambient+ |
| Ledger (elevated) | extend `Transactions` page | `/transactions/` | all |
| Empty states | `EmptyState/*` (certificate/uncharted/constellation/reward-seal) | per-surface | all |
| Living guilloché bg | `LivingGuilloche.tsx` (lazy) | — | shape=all, motion=ambient+ |
| Burin cursor | `BurinCursor.tsx` | — | ambient+ |
| Mood watermark | `MoodWatermark.tsx` | `/forecast/` state | all (time-of-day=full) |

---

## 5. Tech to add in the port (`Personal-FinanceAPP/package.json`)
`motion` (Framer), `lenis` (smooth scroll), `d3-scale`+`d3-shape` (SeaChart only),
`ogl` (~12kb WebGL, lazy import — $0 on first paint/`off`). Reject Three/GSAP/particle libs.
Perf: WebGL lazy + pause offscreen + reduce-motion disables; transform/opacity only; manage
`will-change` on interaction (not permanent); cap concurrent token-blur transitions.

## 6. Reconciliations to apply during the port (don't lose these)
- Prototype `--ease-out .23,1,.32,1` → shipped `0.22,1,0.36,1`.
- Prototype `--boss 5 68% 42%` → shipped `--boss-accent 0 72% 51%`.
- Dark `--debit` +3–4% lightness.
- Replace raw `pointermove` tilt/mouse-tracking with Motion `useSpring` (stiffness~100,
  damping~10) — emil: raw tracking feels mechanical.
- Consolidate per-file living-guilloché + paper-grain into ONE shared layer/component.
- Focus ring via `outline` (not box-shadow).

## 7. Verification (every surface, via chrome-devtools — now permission-allowed)
Matrix: surface × {off,ambient,full} × {light,dark} × {motion,reduce-motion}. Screenshot +
inspect each. Color-law audit (no money figure gets game/WebGL chrome; bosses only red).
Live contrast ≥AA (measured: see token table). Lighthouse for perf; confirm `off` ships ~0
extra weight and WebGL is lazy/paused offscreen. Keyboard reach for ⌘K + every plate.
Then vitest + `./.venv/bin/pytest -q`.
