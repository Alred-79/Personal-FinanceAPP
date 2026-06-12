# 02 — Game-mode system (the one-variable law) + visual foundation

> Implements v4 §10.2, §11 foundations. Frontend-heavy with one small backend piece.

## Context recap

v4's intensity setting `mode ∈ {off, ambient, full}` must be **one variable end to end**, driving
exactly five things: (1) which home route renders (built in 08), (2) design tokens via a
`data-mode` attribute, (3) the copy term catalog, (4) feature-presence flags, (5) server-side
generation on/off. If any feature ever needs more than this variable, it is a fork smell — the
design is wrong, stop and report. **The toggle's crispness is itself a flagship feature**: no
shipped app has it (v4 §2.2). Off mode must remain pixel-identical to today's app.

## Preconditions

- [ ] Package 01 exit criteria all pass (run the suite).
- [ ] `users.game_mode` column exists (01, Migration B).
- [ ] Read `client/src/index.css` and `tailwind.config.js` — the Terminal Ledger tokens
      (Spline Sans Mono, `terminal-blink`, ledger figures, reduced-motion blocks) already exist.
      Build on them; do not replace them.

## Out of scope

The Expedition home and any route switching (08); the Chronicler drawer (07); any game page
content (04+); scanline *animation* beyond a static overlay; renaming existing pages.

## Tasks

### 1. Backend: mode endpoint
- `GET/PATCH /api/user/settings` (or extend the existing settings route — inspect first) to read
  and set `game_mode`. Validate against the enum. PATCH emits no game events (a settings change
  is not a financial action — XP hygiene).
- A `mode != 'off'` check helper that later packages' generation jobs will consult
  (`should_generate_flavor(user) -> bool`). For now used by nothing — but tested.

### 2. `GameModeProvider` (client)
- `client/src/store` or context module: loads mode with user settings, exposes
  `{mode, setMode, terms, flags}`. On change: PATCH server, set
  `document.documentElement.dataset.mode`, swap term catalog — all synchronously, no reload.
- Default before load resolves: `off` (never flash game chrome at a pure-finance user).

### 3. Term catalog (dual-labeling — v4 §4)
- `client/src/terms/terms.off.json`, `terms.ambient.json`, `terms.full.json`. Flat keys
  (`nav.budgets`, `nav.forecast`, `stat.safe_to_spend`, `streak.rebuilding`, …). Start with the
  full key set for existing nav/pages; game-specific keys get added by later packages **in all
  three files in the same commit** (CI-enforced, test 7 below).
- `useTerm(key)` hook: returns `terms[mode][key]`; falls back to `off` value; logs (dev-only) on
  missing key. Plain term must always be reachable: components that show a `full` term get a
  `title=`/long-press reveal with the `off` term (implement the primitive `<Term k="..."/>`
  component that does this automatically — this IS the radical-transparency mechanism).
- Replace hardcoded nav labels in the existing shell with `<Term/>`. Off-mode strings must equal
  the current literals exactly (snapshot-guarded).

### 4. Design tokens & the CRT variable
- Define semantic CSS custom properties under `[data-mode="off"|"ambient"|"full"]` on `:root`:
  `--bg-surface`, `--accent`, `--game-accent` (amber), `--boss-accent` (red), `--radius-panel`,
  `--crt-intensity` (0 / 0.4 / 1). Wire Tailwind utilities to them (Tailwind theme extension —
  keep full class strings, no dynamic class names: JIT can't see computed strings).
- Color law (v4 §11): phosphor green = real money truth; amber = game layer; red = bosses only,
  NEVER user numbers. Encode as tokens now so later packages can't improvise.
- `<ScanlineOverlay/>`: a single fixed-position element using `repeating-linear-gradient`,
  opacity driven by `--crt-intensity`, rendered only when `mode==='full'` AND
  `prefers-reduced-motion` is not set to reduce... note: a *static* gradient is fine under
  reduced motion; only *animated* flicker (not built in this package) is motion-gated. Keep the
  static overlay but cap opacity; no animation here at all.
- Numbers stay effect-free: add a `.figure` guard — the existing tabular-mono ledger class must
  never receive glow/scanline filters (test 10).

### 5. Settings UI
- Intensity selector (Off / Ambient / Full) in Settings: instant, reversible, with one-line
  plain descriptions. Also mirrors into the Keeper sheet later (04) — build the component
  reusable. No confirm dialog, no "are you sure" friction (autonomy; dial-down is a feature).

## Guardrails

- **No component may branch on `mode` directly** except: the provider, `<Term/>`, token CSS, and
  flag checks (`flags.xpBar` etc.). Add an ESLint-able convention: grep test for
  `mode === 'full'` outside the allowed files (test 9).
- Off mode renders today's app **pixel-identically**: same DOM, same strings (snapshot tests).
  If a change is visible in Off mode, you broke the contract.
- No page/route may be created or removed based on mode in this package.
- Don't introduce a second theming mechanism; everything goes through the `data-mode` tokens.

## Test cases

Client (`client/src/__tests__/game-mode.test.tsx` etc., vitest):
1. Provider boots in `off` before settings resolve; no `data-mode="full"` flash (assert initial
   attribute).
2. `setMode('full')` → `document.documentElement.dataset.mode === 'full'`, PATCH called once,
   terms swap in the same render cycle.
3. `useTerm('nav.budgets')` returns "Budgets" in off, the ambient string in ambient, "Mana
   Pools" (or chosen term) in full; unknown key falls back to off-catalog value.
4. `<Term k="nav.budgets"/>` in full mode exposes the off-mode term via accessible attribute
   (title/aria-label) — the one-tap reveal.
5. Off-mode snapshot of the app shell + Settings page matches pre-package-02 snapshot (generate
   the baseline snapshot BEFORE making changes; commit it first).
6. ScanlineOverlay absent from DOM in off/ambient; present in full; opacity reflects
   `--crt-intensity`.
7. **Catalog parity test:** iterate keys of `terms.off.json`; assert the same key set exists in
   ambient and full (and vice versa). This test is the mechanism that forces future packages to
   fill all three catalogs.
8. Mode persists: provider re-mount reads PATCHed value (mock server round-trip).
9. Grep test: `mode === '` / `mode==='` appears only in allowed files (provider, Term, flags,
   tests).
10. `.figure`/ledger-number elements have no `filter`/`text-shadow` in any mode (computed-style
    assertion on a rendered fixture).

Server (`server/tests/test_game_mode_api.py`, pytest):
11. PATCH `game_mode` validates enum (400 on `'rpg'`); persists; GET round-trips.
12. PATCH emits zero `game_events` rows (XP hygiene — settings are not financial actions).
13. `should_generate_flavor(user)` false for off, true for ambient/full.

Integrity:
14. Run the package-01 fingerprint test around a mode change — finance tables untouched.

## Exit criteria

- [ ] All tests above + full suite pass.
- [ ] Manual check: switching Off→Full→Off live changes labels/tokens with no reload, and Off
      looks exactly like before this package.
- [ ] Catalog parity CI test is in place (future packages depend on it).
- [ ] Handoff note appended.

---
*Handoff notes:*
