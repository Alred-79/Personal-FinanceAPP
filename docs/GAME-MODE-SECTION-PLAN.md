# Plan — "Game Mode" landing section with a CRT power-on transition

> Status: **PLAN ONLY (not executed).** Branch context: `feat/polymer-vault-landing`.
> Informed by skills: `frontend-design`, `ui-ux-pro-max`, `impeccable`, `3d-web-experience`,
> `emil-design-eng`, plus `r3f-best-practices` patterns already in the repo.

---

## 1. Context — why this section

The `/welcome` landing already has three "worlds": **Ledger Paper** (light hero/forecast/
instruments) → **Midnight Vault** (dark Security) via the VaultDoor light→dark ceremony. The
product's **game layer** currently shows up only as the small "Cabinet" cluster (a coin + three
lightly-themed cards), which undersells it.

Two background audits (`forecast`-style deep dives) confirmed the game layer is **real, computed,
persisted backend substance — not cosmetic relabeling**:

| Mechanic | Real backing (file) | Concrete numbers |
|---|---|---|
| **Boss battles (debts)** | `server/src/services/game/boss.py` | HP = balance (cents); damage = real payments; **crit when payment > 1.25× minimum**; boss **heals by real APR** (e.g. $5k @ 25% → ~$104/mo); **5 phases break at 20% intervals**; defeat permanent (seal/banish) |
| **XP — money-moves only** | `server/src/services/game/xp.py` | Registry law (test-enforced): bill-on-time **+25**, under-budget day **+10**, payment posted **+20**, what-if committed **+20**… **logins / views / mode-changes = 0 XP**; level = `⌊√(xp/120)⌋` |
| **Expedition (monthly run)** | `server/src/services/game/expedition.py` | Forecast → 3-act map; score `0.5·green + 0.3·obj + 0.15·boss + 0.05·verbs`; **prestige = `⌊10·√score⌋`** on month-seal; rank **E→S** |
| **Heat (constraints)** | `server/src/services/game/heat.py` | Cap 75/50/25% of baseline → **1/2/3 heat**; verified underspend **auto-sweeps into the boss or a goal**; burnout guards |
| **Challenges (tiered)** | `server/src/services/game/challenges.py` | T1 code-judged from posted txns **+25**, T2 **web-fact-checked (Tavily)** **+10**, T3 self-report **+0** |
| **Game mode dial** | `server/src/services/game/mode.py` | `off / ambient / full`; **off is pixel-identical** to the plain app; full adds a **CRT effect** (CSS var intensity) |

Plus real streaks (rebuilding floor + ward system) and derived RPG stats (Vitality = runway,
Armor = on-time-bill ratio, …). **Verdict: enough substance for a full section.**

### Honesty constraints (load-bearing — do not violate)
- **It is a MODE that is off by default.** Frame the section as *opt-in* ("turn it on, or leave
  it off"), never as the default experience. This is honest **and** a selling point.
- **Drop the cosmetic pieces from the hero of the section.** The "minted coins / Goals Cabinet"
  has **no backend minting mechanic** — it's frontend flavor. Lead with boss / XP / expedition,
  which are real. Bestiary creature *names* and the "Keeper" persona are flavor over real systems
  — fine as dressing, never as the claim.
- Every on-screen number must be a real mechanic's real value (HP in $, +25 XP, ×1.25 crit,
  prestige `⌊10√score⌋`, 5 phases). No invented stats.

---

## 2. Decision (confirmed with user)

**Full dedicated section + a "power-on" transition of a different kind than the vault.** It
**replaces the current Cabinet cards** and leads with the real mechanics (boss HP/crit/phases,
XP-from-real-moves, expedition + prestige). The transition mirrors a **real feature**: the product
literally has a game-mode toggle with a CRT effect, so the section *boots up* like a CRT.

**Fate of the existing `Cabinet.tsx`:** superseded. Keep the struck **GOOD STANDING coin** but
re-cast it as the section's **rank/prestige emblem** (it earns its place as the "good standing"
trophy). Remove the three cosmetic cards. Goals stay represented by the Forecast (safe-to-spend +
goal pace) and the hero lede.

---

## 3. Design direction — avoid the category reflex

`impeccable`'s AI-slop test, applied:
- **First-order reflex (reject):** "gamified fintech" → **neon arcade** (cyan/magenta glow, generic
  pixel coins). Do not build this.
- **Second-order reflex (reject):** the "not-arcade" escape hatches — **8-bit pixel-art** or
  **navy + gold "premium game"**. Also tells.
- **Our lane (commit):** the product's *own* idiom — an **engraved financial CRT terminal that
  boots into a roguelike HUD.** Think a 1980s trading/teletype terminal crossed with the existing
  banknote engraving: **phosphor monochrome on near-black, scanlines, bloom, a faint barrel curve
  and vignette, a slow flicker**, with the engraved gold + credit/debit inks **preserved** for the
  money/HP semantics. It's the third "world": *paper → vault → terminal.*

This is distinctive because it is *specific to a ledger product* (a finance terminal, not an
arcade), and it reuses the repo's engraving DNA rather than importing a foreign aesthetic.

### Type & color
- **Type:** lean into the repo's existing **`Spline Sans Mono`** for the HUD (terminal voice);
  keep **Fraunces/display** only for the section title. Monospace = tabular figures for HP/XP/
  prestige (prevents layout shift — `ui-ux-pro-max: number-tabular`). No new fonts.
- **Color (new tokens, scoped to the section):** a **phosphor** accent — pick **amber-phosphor**
  (`oklch(~0.82 0.16 75)`) *or* **green-phosphor** (`oklch(~0.86 0.18 150)`) on the existing
  near-black vault bg. **Amber recommended**: it's warmer, rarer than the green-terminal cliché,
  and sits closer to the brand gold so the worlds feel related. **Preserve the color law:** money
  HP figures use `--debit`/`--credit`/`.figure` (never the phosphor), phosphor is chrome only.
- **Contrast (mandatory, `impeccable` + `ui-ux-pro-max`):** phosphor text on near-black must hit
  **≥4.5:1** body / ≥3:1 large. Verify the chosen phosphor L; bump lighter if close. The scanline
  overlay must **not** drop effective contrast below AA — keep scanline opacity low (≤8%).

### Composition — NOT another card grid
`impeccable`: *"identical card grids"* and *"cards are the lazy answer"* are banned. The current
Cabinet is three equal cards — the new section must read as a **single HUD screen**, asymmetric:

```
┌─ TERMINAL FRAME (barrel + vignette + scanlines) ───────────────────────┐
│  > game mode_                                   [ OFF · AMBIENT · FULL ]│  ← prompt + real dial
│                                                                         │
│  ┌─ BOSS (focal) ───────────────────────────┐   ┌─ STATS sidebar ───┐  │
│  │  THE GILDED DINING SHADE        ☠ tier 3 │   │ VITALITY  ▓▓▓░ 4mo │  │
│  │  HP ███████████░░░░░░  $3,180 / $5,000    │   │ ARMOR     ▓▓▓▓ 92% │  │
│  │  [ make a payment ]   −$250  ⚡CRIT ×1.25 │   │ MIGHT     ▓▓░░ +$210│  │
│  │  phase 3 of 5 broken · +$104 APR heal/mo  │   │ STREAK   day 14 ◆◆ │  │
│  └───────────────────────────────────────────┘   └───────────────────┘  │
│                                                                         │
│  EXPEDITION ▸ run score 0.78 · GREEN ×3 · prestige +8 ▸ rank C          │  ← ticker/footer
│  ▁▁▁▁ XP ▕███████████████░░░░░▏ LV 4 · 1,080 XP ▁ earned only from real moves ▁│ ← HUD XP bar
└─────────────────────────────────────────────────────────────────────────┘
```

- **Boss** is the focal panel (largest, left). **Stats** ride a thin right sidebar. **XP bar** spans
  the full bottom edge (classic HUD). **Expedition** is a one-line ticker above the XP bar. The
  **dial** sits top-right as the real Off/Ambient/Full control. One primary interaction per
  altitude (`ui-ux-pro-max: primary-action`).
- Avoid the banned **uppercase eyebrow on every block** — use a **blinking terminal prompt**
  (`> game mode_`) as the section's voice instead of another `dept-label`.

---

## 4. The beats (content — all real)

Lead with the strongest, most concrete mechanics; relegate the cosmetic to dressing.

1. **The dial (interactive, honest).** A real `Off · Ambient · Full` control. Toggling it **dials
   the section's own intensity live** — Off: the HUD goes quiet/plain (mirrors the real "pixel-
   identical off"); Ambient: HUD visible, gentle; Full: CRT bloom + flicker + roast copy. This *is*
   a real setting, so it's honest, and it teaches the feature by letting you touch it.
2. **Boss battle (anchor, interactive).** A debt-beast with **HP = balance**. A `make a payment`
   button (or drag) drops HP; a payment over **1.25× the minimum** triggers a **CRIT** (gold flash,
   bigger chunk, `⚡CRIT`); each simulated month the boss **heals by APR** (a small red tick up);
   crossing a **20% phase** shatters a bar segment with a stamp; zero HP → **VANQUISHED** seal
   (your choice: *seal* the trophy or *banish*). Caption the real rule set succinctly.
3. **XP — the anti-dark-pattern hook.** An XP bar that fills **only from verified money moves**.
   Show a short ledger: `Bill paid on time +25 · Under-budget day +10 · Payment posted +20` beside
   a struck-through `Logged in +0 · Opened the app +0 · Changed a setting +0`. Level `⌊√(xp/120)⌋`.
   This is the line most "gamified" finance apps **cannot** truthfully say — make it the headline
   idea of the section.
4. **The Expedition (the loop).** Each month is a run: the forecast as a 3-act voyage, scored, with
   **prestige minted** (`⌊10·√score⌋`) on month-seal, driving rank **E→S**. A compact run-summary
   ticker + a one-shot **prestige strike** animation; the GOOD STANDING coin becomes the rank seal.
5. **(Secondary, optional row) Heat + Challenges.** Compose a cap (75/50/25% → 1/2/3 heat) →
   **verified underspend sweeps into the boss/goal**; challenges **T1 code-judged · T2 web-checked ·
   T3 self-report (0 XP — "lying earns nothing")**. Include only if it doesn't bloat the section;
   otherwise hold for a v2.

---

## 5. The "power-on" transition

A **scoped, local** boot — *not* a full-page theme flip like the VaultDoor (one ceremony per page
is enough). The section's terminal **powers on as it scrolls into view**, then powers down/quiets
as it leaves.

Boot sequence (≈900ms total, `prefers-reduced-motion` → instant-on, no movement):
1. **Black → a single bright horizontal scanline** sweeps top→bottom (`clip-path`/WAAPI, off the
   main thread per `emil`: *"CSS animations beat JS under load"*).
2. **Bloom flash** (short white→phosphor `opacity` pulse) + a faint **degauss wobble** (1 cycle of a
   subtle `filter` distortion or transform skew).
3. **Phosphor grid + scanline overlay fade up**; vignette + barrel settle.
4. **HUD boots in** with a **stagger** (30–60ms) — title, then boss panel, then stats, then the XP
   bar fills left→right once. Reveals must **enhance an already-visible default** (`impeccable`):
   never gate content visibility on the boot class, or it ships blank on hidden tabs/headless.

`useInView({ once: true })` (already used) triggers boot; a `usePointerFine` + `prefers-reduced-
motion` gate decides flicker/bloom vs. static. Mirrors the existing `useThemeJourney`/`Backdrop`
capability pattern.

---

## 6. Motion spec (`emil-design-eng` + `ui-ux-pro-max`)

- **Custom ease-out** for entrances: `--ease-crt: cubic-bezier(0.23, 1, 0.32, 1)` (the built-ins
  are too weak). **Never `ease-in`** on entrances; **never `transition: all`.**
- **Durations:** boot beats 150–300ms each (button-press 100–160ms; the full boot may run longer as
  a *rare/first-time marketing* moment, which `emil`'s frequency table permits). Exit/power-down
  **faster than enter** (~60–70%).
- **HP bar drain:** `clip-path: inset(... )` or `transform: scaleX()` (GPU; interruptible) — *not*
  width. **Crit** = a quick `scale(1.04)` punch + phosphor/gold flash, then settle. **Never animate
  from `scale(0)`** — the prestige strike starts at `scale(0.4)`+opacity, not 0.
- **XP fill** = `transform: scaleX` left-origin, one pass, `--ease-crt`.
- **Use CSS transitions, not keyframes, for any rapidly-retriggerable state** (payment taps);
  **WAAPI** for the programmatic scanline sweep. Framer Motion (`motion/react`, already a dep) for
  the in-view boot stagger — but use full `transform:"translate…"` strings, **not** `x`/`y` shorthand
  (those aren't HW-accelerated and drop frames under load).
- **Reduced motion** = *fewer & gentler, not zero*: keep the phosphor look and opacity/color, **drop
  the flicker, the scanline sweep, the degauss, and all positional motion**; the HUD simply appears.
- **Flicker** = `opacity` only (cheap), very subtle, `full` mode only, disabled on reduced-motion.

---

## 7. Tech / architecture

### CRT effect — CSS-first, WebGL optional (`3d-web-experience` anti-patterns)
WebGL post-processing for a marketing band is *3D-for-3D's-sake* risk. Build the CRT in **CSS** as
the always-on base, with an **optional** WebGL shader enhancement gated exactly like the coin:
- **CSS CRT (base, ships everywhere):**
  - Scanlines: a fixed pseudo-element `repeating-linear-gradient(transparent 0 2px, rgba(0,0,0,.06) 2px 3px)`.
  - Phosphor glow: `text-shadow`/`box-shadow` in the phosphor hue on HUD glyphs.
  - Vignette + barrel: radial-gradient mask + a small `border-radius` + `scale`/`perspective` curve.
  - Chromatic fringe: a duplicated layer or split `text-shadow` (tiny red/blue offset), `full` only.
  - Flicker: low-opacity keyframe, `full` only, reduced-motion-off.
- **WebGL CRT (enhancement, gated):** a single fullscreen R3F quad with a fragment shader doing
  scanline + bloom + barrel + chromatic, composited over a snapshot/HTML layer. **Gate behind**
  `usePointerFine() && webglSupported() && !prefersReducedMotion` (reuse the repo's `ReliquaryLazy`/
  coin probe), **lazy-loaded** as a separate chunk, with the CSS version as the guaranteed fallback.
  Recommend shipping **Phase 1–5 on CSS only**; add the shader in Phase 6 if it earns its weight
  (`r3f-best-practices`: keep it off the main thread, dispose on unmount, cap DPR).

### Files (new), under `client/src/pages/Landing/`
- `sections/GameMode.tsx` — the section orchestrator (replaces `<Cabinet/>` in `Landing.tsx`).
- `sections/game/useGameBoot.ts` — in-view boot trigger + capability/reduced-motion gating.
- `sections/game/BossPanel.tsx` — interactive HP/crit/heal/phase/defeat (the anchor).
- `sections/game/XpBar.tsx` — the "XP from real moves only" HUD bar + ledger.
- `sections/game/StatsRail.tsx` — Vitality/Armor/Might/Streak (derived, real).
- `sections/game/ExpeditionTicker.tsx` — run score + prestige strike + rank seal (reuse the coin).
- `sections/game/IntensityDial.tsx` — Off/Ambient/Full, drives a section-scoped CSS intensity var.
- `sections/game/crt.ts` (or extend `landing.css`) — CRT tokens + scanline/glow/flicker classes.
- *(Phase 6, optional)* `sections/game/CrtShader.tsx` + `crtShaderLazy.tsx` — gated R3F enhancement.
- CSS appended to `landing.css` under a clearly-commented `/* === Game Mode (CRT) === */` block,
  scoped with a `.gm-` prefix and a `.gm-on`/intensity data-attr so **off mode stays inert**.

### Reuse (don't rebuild)
`Rise`, `AnchorLink`, `Magnetic`, `useReducedMotion`, `usePointerFine`, `useInView`, the engraving
`Seal`/`Stamp`/`Certificate`/`Guilloche`, the struck coin from the old Cabinet, and the existing
`--gold`/`--credit`/`--debit` tokens + `.figure` color law.

---

## 8. Accessibility (`ui-ux-pro-max` §1, `impeccable`)
- **Bars are meters:** `role="meter"` + `aria-valuenow/min/max` + a **visible text value** on the
  HP and XP bars (color-not-only — phosphor/red is never the sole signal).
- **The dial** = real buttons, **≥44px** targets, keyboard-operable, `aria-pressed`, visible focus
  ring (never removed). Boss `make a payment` = a real `<button>` with `:active` `scale(0.97)`.
- **Contrast** verified for phosphor-on-black at AA, *with the scanline overlay applied*.
- **Reduced motion** path defined (instant-on, no flicker/sweep/positional motion; keep color).
- **Don't gate content visibility** on the boot animation (renders fully without JS/motion).
- Money figures keep tabular mono + the credit/debit law; no info by color alone.

## 9. Performance
- Scanlines/vignette = one fixed overlay; flicker = opacity-only; **transform/opacity only** for all
  motion; no layout-animating properties.
- WebGL is **opt-in, gated, lazy, DPR-capped, disposed on unmount**; CSS path is the default.
- Boot work batched in rAF; `content-visibility`/`will-change` used sparingly; keep per-frame < 16ms.

---

## 10. Build phases (each: implement → `tsc` → `vitest` → `vite build` → chrome-devtools verify
incl. reduced-motion + 375px mobile + AA contrast)
1. **Scaffold + CSS CRT + power-on boot** (scanline sweep, glow, vignette, flicker, intensity var,
   reduced-motion + capability gating). Swap `Cabinet` → `GameMode` in `Landing.tsx`; remove the
   three cosmetic cards; re-home the coin as the rank seal.
2. **BossPanel** — interactive HP/crit/heal/phase/defeat (the anchor).
3. **XpBar** — the "XP only from real money moves" ledger + level curve.
4. **StatsRail + ExpeditionTicker** — derived stats + run score + **prestige strike** + rank.
5. **IntensityDial** wired to live section intensity (Off/Ambient/Full) + optional Heat/Challenges
   secondary row (only if it doesn't bloat).
6. *(Optional)* **WebGL CRT shader** enhancement, gated + lazy, CSS fallback retained.

## 11. Verification checklist
- `tsc` clean · `vitest` green (current baseline **246**) · `vite build` clean.
- Live `/welcome`: boot fires once in view; boss payment → HP drop, crit flash, phase shatter,
  defeat seal; XP bar fills; dial changes intensity; prestige strike plays once.
- **Reduced motion:** instant-on, no flicker/sweep/movement, content fully present.
- **Mobile 375px:** HUD reflows (boss stacks above stats; XP bar full-width); no horizontal scroll.
- **Contrast:** phosphor + money figures pass AA with scanlines applied.
- **Off-mode honesty:** the section reads as an *optional mode*; no invented numbers; cosmetic bits
  stay as dressing, real mechanics carry the claims.

## 12. Open questions for you
- **Phosphor color:** amber (recommended, warmer/rarer, near the brand gold) vs. green (classic
  terminal).
- **Placement:** replace the Cabinet slot (between Security and FinalCTA), or move the game section
  to the very end as the final flourish before the CTA?
- **Scope of v1:** beats 1–4 (dial, boss, XP, expedition) only, or include the Heat/Challenges row
  (beat 5) now?
- **WebGL CRT:** ship CSS-only v1 and add the shader later (recommended), or build the gated shader
  in v1?
