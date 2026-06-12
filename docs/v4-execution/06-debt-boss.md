# 06 — Debt Boss Battles (the flagship)

> Implements v4 §7.1 + the juice system (§11) and the closure card. The marketed sentence (R11):
> *"your real payments, verified by your bank, with a defeat date computed from your actual
> cashflow — and the win is the day the account closes."* The boss metaphor is the skin on that
> sentence.

## Context recap

One debt account = one boss (concentration — Kettle et al.); payments posted via Plaid = damage;
above-minimum = crit; APR accrual = boss heal; missed real bill = boss *empowered* (agency
points at the debt, never the user); defeat-by-date from `project_cashflows`, live-updating;
**victory = the closure event** with an informed seal-vs-banish choice; multi-phase HP for large
debts (every 20%); smallest-first default with a one-time informed override showing the user's
own APR delta in dollars. Habit-monsters are computed (no schema) from discretionary overruns +
subscriptions.

## Preconditions

- [ ] Packages 01–05 pass.
- [ ] v1 generic rule target verified usable for a new target kind (`pay_liability`).
- [ ] Read `subscription_service.py` / `recurring_service.py` for the recurring-stream shapes
      habit-monster detection will consume.

## Out of scope

LLM-generated names/taunts (07 — bosses get deterministic placeholder names like "the
<Creditor> Wyrm" from a template until then), the bestiary *surface* (09), Heat sweeps (09),
regret-monster (09), expedition map placement (08).

## Tasks

### 1. `Liability` model + migration + CRUD
- Fields: `user_id, name, kind (credit_card|loan|bnpl|other), principal_cents,
  apr_bps, minimum_payment_cents, due_day, linked_account_id NULL, linked_plaid_account NULL,
  status (active|dormant|defeated_sealed|defeated_banished), opened_at, defeated_at NULL`.
- CRUD API + a plain management UI (works in Off mode — it's a finance feature; the boss render
  is the skin). Manual entry supported; link to a Plaid liability account where one exists.
- **This is the one financial-truth-adjacent table game code may write** — but only via its own
  service (`liability_service.py`), never via fold handlers. Balance display always derives from
  payments/corrections, with a manual "reconcile balance" action for drift (creates an
  adjustment record, never silently edits).

### 2. Boss projection — `boss_state`
- HP = current balance (cents). Damage events derive from `TxnPosted` matched to the liability
  (linked account, or payee-match rule the user confirms once). `BossDamaged.v1 {amount, crit}`;
  crit when payment > minimum × 1.25.
- `BossHealed.v1` monthly APR accrual (computed deterministically on month close from
  apr_bps — show the real interest number on tap; the heal IS the interest, that's the lesson).
- `BossEmpowered.v1` when a tracked recurring bill on that debt is missed (detected via
  recurring stream absence) — visual menace only; it adds NO HP beyond the real late
  fee/interest when those post (no fictional penalties).
- Phases at each 20% of starting HP: `BossPhaseBroken.v1`, idempotent per phase index.
- Defeat-by-date: recompute from `project_cashflows` + current payment pattern on every damage
  event and on Grace transitions. Date moving OUT under Grace = "the boss retreats" copy, never
  "you fell behind" (banned-language list below).
- Victory: balance ≤ 0 → `BossDefeated.v1`, then the seal/banish choice:
  - **Seal** (close account) / **Banish** (keep open at zero). Static educational copy on
    credit-score effects (utilization/age) — plain prose, NO LLM, no recommendation. Choice
    recorded (`BossSealed/BossBanished.v1`). Overpay → HP clamps at 0; surplus is just the real
    refund/credit reality, never negative HP.
- **One active boss** (concentration): selection screen defaults to smallest balance, with the
  one-time informed override — compute and show THIS user's dollar interest delta between
  snowball and avalanche orderings (deterministic amortization calc; show both totals).
  Other debts render as dormant silhouettes (name + tier glyph only, no HP bar).

### 3. Habit-monsters (computed, no schema)
- Derivation (a pure read-model): discretionary category ≥ 130% of baseline pace mid-month →
  minor monster; subscription with rising price or 3+ months unused (no matching usage txns) →
  "creeper". Damage = verified under-budget days (05's GREEN verdicts scoped to the category)
  and cancellation — which proves itself by the FIRST ABSENT expected charge
  (`recurring_service` stream goes silent past its due window). Set that expectation in copy:
  "the creeper falls when its next bill fails to appear."
- Cap: ≤2 visible habit-monsters at once (pest avoidance); essentials NEVER spawn monsters.

### 4. Seeded ASCII rendering
- `client/src/lib/asciiCreature.ts`: deterministic glyph-grid creature from
  `seed = hash(kind + creditor_or_merchant_normalized)` — mirrored-mask algorithm (generate a
  half-grid of glyph density from the seeded PRNG, mirror it, map density→glyph ramp). Same
  seed → same art, always (recognition is the feature). Size tiers by balance bucket.
- Render in amber/red tokens per the color law: boss art red-accented; user numbers never red.

### 5. Juice — payoff events ONLY (v4 §11)
- Build the celebration system here, once, with a hard allowlist:
  `JUICE_EVENTS = {BossDamaged(crit), BossPhaseBroken, BossDefeated, BossSealed, GoalFunded,
  RuleExecuted(sweep), LevelUp}`. Damage numbers in display-size tabular mono with count-up;
  phase-break flash; closure gets the full ceremony.
- **Structurally forbidden:** juice on `TxnPosted` generally (a purchase is never celebrated),
  on near-misses, on streak events beyond the standard toast. The allowlist test (below) is the
  enforcement.
- All animation behind `prefers-reduced-motion` with static fallbacks.

### 6. Closure card
- 1200×630 share image (client-rendered → canvas/PNG): archetype-free for now — boss name, tier
  glyph, duration ("defeated in 7 months"), zero dollar amounts by default; amounts only with
  an explicit "include numbers" toggle. This is the distribution surface — treat layout quality
  as part of this package, not polish.

## Guardrails

- **Agency-language lint (test 14):** banned in all boss templates: "you failed", "you lost",
  "you fed", "you fell", "your fault", "missed payment" as user-attributed phrasing. The boss
  "holds ground", "regroups", "retreats"; the user never takes narrated damage.
- A mis-matched payment (categorization error) must be fixable by the user in one action
  (unlink txn from boss → emits `TxnCorrected`-style compensation, clamp rules apply) — errors
  resolve pro-player, never require support.
- No boss logic in fold handlers writes to `liabilities` (folds project; the service mutates).
- The Chronicler does not exist yet — and even in 07+, it stays silent on seal-vs-banish
  (Law 3). The educational copy ships here as static text.
- Defeat-by-date is the forecast's number — never an LLM's, never smoothed for optimism.

## Test cases (`server/tests/test_game_boss.py`, client `boss.test.tsx`)

Damage & HP:
1. Posted payment on linked account → `BossDamaged` exactly once (idempotent on sync replay);
   HP = principal − Σdamage ± corrections.
2. Crit threshold: minimum×1.25 boundary (at, below, above).
3. `TxnCorrected` reducing a payment → HP rises (truth), XP unchanged (clamp), no "damage
   undone" celebration (juice allowlist has no negative events).
4. `TxnReversed` payment → HP restored exactly; boss not re-celebrated on re-payment with new
   txn id (different idempotency key → allowed, but phase events stay idempotent per index).
5. Overpay → HP clamps 0; `BossDefeated` fires once.

Heal & empower:
6. Month close → `BossHealed` equals real APR math (fixture: 24% APR on $1,000 → expected
   cents); tap-reveal exposes the real interest figure.
7. Missed recurring bill on the debt → `BossEmpowered` once per occurrence; HP unchanged until
   real fees post.

Phases & defeat-by-date:
8. $5,000 boss: phase events at 4,000/3,000/2,000/1,000/0 — each exactly once across replays
   and rebuilds.
9. Defeat-by-date recomputes on damage (fixture: extra $100 pulls the date in); Grace pushes it
   out AND copy key switches to the "retreat" variant (assert template id, not prose).

Selection & ordering:
10. Default ordering = smallest balance; override screen shows both orderings' total-interest
    dollars (golden amortization fixtures: 2 debts, known APRs → known delta); choice persists;
    re-prompt never (one-time).
11. One-active enforcement: activating boss B with A active → 409/blocked; A's silhouettes
    render without HP bars (client assertion).

Closure:
12. Balance-zero → seal/banish modal (client); each choice records its event; status
    transitions; closure card renders with zero "$" glyphs by default, includes them only with
    the toggle on.
13. Sealed boss is permanent: no event can resurrect `defeated_*` status (attempt → error).

Monsters:
14. Agency-language scan over every boss/monster template (the banned list above).
15. Habit-monster spawn matrix: 130% discretionary pace → spawns; essential category 200% →
    never; cap of 2 enforced (3rd-worst category waits).
16. Cancellation: stream due day passes with no charge → monster defeated event; charge
    arrives 3 days late → defeat reversed quietly (no shame copy), pro-player grace window
    honored (no MISS-equivalent).
17. Unused-subscription detection: 3 months without usage-matched txns → creeper flagged;
    user "keep it" action dismisses permanently (respect the choice, no re-nag — assert
    suppressed).

Rendering & juice:
18. ASCII determinism: same creditor seed → identical grid across runs/platforms; different
    creditors → different grids (hash sanity); snapshot 3 fixtures.
19. Juice allowlist walk: iterate all event types; assert celebration registry ⊆ JUICE_EVENTS;
    a `TxnPosted` purchase event triggering juice = test failure.
20. Reduced-motion: celebration renders static variant (computed-style assertion).

Auto-attack & integrity:
21. Round-up rule with `target_kind=pay_liability` → `RuleExecution` → `BossDamaged` flows
    end-to-end... **only if** v1 rules engine actually executes allocations of this kind —
    otherwise the rule records intent and damage applies when the real payment posts. Verify
    which semantics v1 ships and test THAT (document in handoff).
22. Fingerprint test: a full boss lifecycle (create → damage → phases → defeat → seal) touches
    only `liabilities` + game tables; transactions/accounts/budgets/goals untouched. Rebuild
    `boss_state` reproduces live.

## Exit criteria

- [ ] All tests pass; suite green; rebuilds clean.
- [ ] Manual: create a $500 fixture debt, post payments, watch HP/phases/defeat-by-date move;
      defeat it; both closure paths work; card exports.
- [ ] Juice allowlist + agency-language tests are wired into CI (later packages extend them).

---
*Handoff notes:*
