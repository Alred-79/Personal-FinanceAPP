> **⚠️ ARCHIVED — 2026-06-17, historical.** An early critique of the HTML prototypes; the prototypes have since shipped to React. Kept for the record. Current forward doc: **`HANDOFF-TIER4.md`** (one level up).

# Deep Design Review — the 4 page prototypes

> Reviewed with **emil-design-eng** (motion/craft), **impeccable** (frontend rules),
> **ui-ux-pro-max** (a11y/UX checklist). Verified live in Chrome (chrome-devtools MCP):
> rendered every page, opened the Command Deck + diff plate, measured real contrast ratios
> in light & dark. Date 2026-06-15.
>
> **Verdict:** High-quality prototypes. The hard parts (color law, reduce-motion, the diff
> plate, mode fallbacks, custom easing, `.figure` guards) are already right. The fixes below
> are polish + accessibility + a few emil-specific motion corrections — none are structural.

## What's already excellent (keep)
- **Color law holds** — every money value is `.figure` (filter/text-shadow stripped);
  amber = game, `--boss` red is isolated to the boss/HP only. Verified visually on game-home.
- **Contrast passes WCAG AA** (measured live): light — muted 5.26, debit 6.03, credit 6.97,
  serial 5.63; dark — muted 6.14, credit 6.98, gold-glyph 7.97, meta 5.66.
- **Reduce-motion is thorough** — every file kills the burin + ink canvas, drops transforms,
  neutralizes the page-recede. This is better than most production apps.
- **Custom easing vars** already present (`--ease-out: cubic-bezier(.23,1,.32,1)` etc.) — matches
  emil's "built-in easings are too weak" rule.
- **The Command Deck diff plate** is the standout — engine-verified caption, red-strikethrough
  removals / green additions, Authorize-stamp, honest "nothing moves until you stamp" footnote.
- Mode fallback done right (`html:not([data-mode="full"]) .terr-visual{display:none}` →
  ambient shows the plain engraved schedule).

---

## ✅ RESOLUTION (applied 2026-06-15, verified live in Chrome)

The user chose "fix the prototypes first." Applied across ALL 4 files + re-verified with
chrome-devtools (focus, roles, labels, interactions):
- **P0 focus rings** — `:focus-visible{outline:2px solid gold; offset:2px}` (used OUTLINE not
  box-shadow, because `.summon`/`.btn` set their own box-shadow and would override a
  box-shadow ring — confirmed live the outline paints on every control).
- **P0 command-deck a11y** — summon is now a `<button aria-label aria-keyshortcuts>`; input is
  `role=combobox aria-expanded aria-controls aria-activedescendant`; `#suggest` is
  `role=listbox`, options `role=option aria-selected`; `select()` keeps `aria-activedescendant`
  synced; deck has a Tab **focus trap** + **focus restore** to the trigger on close; deckbody
  is `aria-live=polite` so the agent reply + diff are announced.
- **P0 labels/hidden** — decorative `#living`/`#ink` canvases `aria-hidden`; data canvases
  (`#voyage`,`#terr`,`#sky`) given `role=img` + descriptive `aria-label`; all toolbar buttons
  labeled; ledger `firstrun` toggles `aria-pressed`.
- **P1 emil motion** — plates now use `var(--ease-out)` (not bare `ease`); manicule/row
  transitions name properties (no `all`-shorthand).
- **P2 hover gating** — `.plate/.btn/.mod/.row/.summon` hover transforms wrapped in
  `@media (hover:hover) and (pointer:fine)`; focus-visible provides the keyboard equivalent
  (manicule also reveals on `:focus-visible`).

**Deferred to React port (Phase 3), noted in source:** spring-based tilt (Motion `useSpring`
instead of raw pointermove), `will-change` lifecycle management, dark-`--debit` +3–4% lightness
nudge, consolidating the per-file living-guilloché/paper-grain into one shared layer, capping
concurrent token-blur transitions. These need React/build infra, not prototype edits.

## Prioritized fix list (original — for reference)

### P0 — Accessibility blockers (fix before React port)

1. **Keyboard can't reach the page's interactive bits / no visible focus ring.**
   `cursor:none` hides the system cursor app-wide and the only affordances are pointer-driven
   (`pointermove`/`click`). There are no `:focus-visible` styles, and the command-deck options,
   loadout chips, ledger rows, coins respond to `pointermove`/`click` only. Keyboard + screen-
   reader users are stranded.
   - Add a strong `:focus-visible` ring (reuse the app's engraved double-ring) on every
     button/input/option/row.
   - Deck options need `role="option"` within a `role="listbox"`, and the input needs
     `role="combobox" aria-expanded aria-activedescendant` pointing at the selected option.
   - Don't rely on `pointermove` to select — also drive selection from arrow keys (the deck
     does this) and ensure Enter/Space activate.

2. **Decorative canvases need to be hidden from AT and the burin must never trap input.**
   `#living` and `#ink` are decorative — add `aria-hidden="true"` (nib already has it). Confirm
   they stay `pointer-events:none` (they do). Good; just make it explicit on the canvases.

3. **Icon-only / glyph controls lack labels.** The toolbar (`◐ theme`, `⛯ mode`, `⊕ first run`),
   the manicule `☞`, and glyph buttons need `aria-label`s; the ✶/☞/⛆ glyphs are emoji-ish
   pictographs used as UI — give text alternatives (ui-ux-pro-max: `no-emoji-icons`,
   `aria-labels`).

4. **The Deck is `role="dialog" aria-modal` but doesn't trap focus.** Tab can leave the deck
   into the dimmed page behind. Add a focus trap + restore focus to the summon button on close
   (ui-ux-pro-max: `escape-routes`, `focus-management`; emil doesn't cover this but it's table
   stakes).

### P1 — emil motion corrections

5. **Plates use generic easing, not the custom curve.** `.plate{transition:box-shadow .25s ease,
   transform .12s ease-out}` — emil: replace bare `ease`/`ease-out` with `var(--ease-out)` for
   consistency with the rest of the system (the vars exist; they're just not used here).

6. **Tilt is wired to raw `pointermove` with no spring → feels artificial under load.**
   emil's exact rule: mouse-tracking visual changes feel mechanical without momentum. In React,
   drive the tilt through Motion's `useSpring` (stiffness ~100, damping ~10). For the prototype
   it's acceptable, but flag for the port.

7. **`transition:.2s` shorthand on ledger rows** (`.row{transition:background-color .2s,
   transform .2s}`) — fine, but the manicule uses `transition:.2s` (all-properties shorthand).
   emil/impeccable: name the properties (`opacity .2s, transform .2s`) — avoid `all`.

8. **Coin entrance / ignite should never start from scale(0).** Verify the mint coin and the
   goal-ignite begin at `scale(.9–.95)+opacity`, not `scale(0)` (emil: "nothing appears from
   nothing"). The stamp keyframes already do this correctly (start 1.7→settle) — mirror that.

9. **Page-recede on deck open animates `filter` (saturate/brightness).** `filter` is not a
   cheap GPU property; under load this can jank. emil/perf: prefer animating `opacity` of an
   overlay veil (already present) and a `transform:scale` — drop the `filter` transition or
   gate it to non-reduced-motion + accept the cost knowingly. Minor.

### P2 — polish / craft

10. **Stagger timing on the diff rows is content-length-derived** (`c.line.length*4+i*90`).
    emil: stagger 30–80ms between items; 90ms is slightly long and the `length*4` base can get
    large. Use a fixed base (~120ms) + 50ms stagger.

11. **Token-reveal blur on the agent reply** (`.tok{filter:blur(2px)}`) is good (emil's
    "blur masks imperfect transitions"), but it animates `filter` per-token — many simultaneous
    filter transitions. Cap concurrent in-flight tokens or accept it's a one-shot.

12. **`will-change` is set permanently** on `#nib`, `.btn` (`will-change:transform`). impeccable/
    perf: `will-change` left on forever costs memory; set it on interaction start, remove after.
    Minor at this scale.

13. **No `@media (hover:hover)` gate on hover transforms.** Touch already gets `cursor:auto` and
    the burin is disabled, but `.plate:hover`, `.mod:hover`, `.row:hover` still fire on tap on
    touch devices (false hover). emil: gate hover-only motion behind
    `@media (hover:hover) and (pointer:fine)`.

14. **Single shared paper-grain + living-guilloché re-declared per file.** Fine for prototypes;
    in React these become one shared component/layer (Phase 2 consolidation).

### P3 — nits
- Dark-mode `--debit` is 4.67:1 — passes AA but tightest margin; nudge lightness +3–4% for
  headroom on small tabular figures.
- `kbd` styling is lovely; ensure the `⌘K` summon hint is also a real focusable button (it's a
  `<span class="summon">` with a click handler — make it a `<button>`).
- Deck `aria-label="Command Deck"` good; add `aria-live="polite"` on the reply region so the
  agent's inked-in answer is announced to screen readers.

---

## Cross-cutting takeaways for the React port (Phase 3)
- Build ONE `<FocusRing>` + a11y primitives pass first; the prototypes are pointer-first and
  every page inherits the same gaps.
- Replace raw `pointermove` tilt/mouse-tracking with Motion `useSpring` globally.
- Make the burin cursor a single component: ambient/full-only, off under reduce-motion AND on
  touch (already the logic), native caret over inputs (already done on `#cmd`), plus a global
  user setting to disable it (accessibility).
- Centralize easing/duration tokens and the living-guilloché + paper-grain as shared layers.
- Keep the diff plate exactly as designed — it's the strongest piece.
