# persFin — Implementation Spec (now → app completion)

**Date:** 2026-06-18 · **Branch of record:** `feature/analytical-layer`
**Status:** the single, detailed build bible. The `MASTER-ROADMAP` sequences; **this doc is what you implement from**. It supersedes the scattered plan docs for execution and folds in the RLS reality that post-dates them. Every reuse point is cited to real code.

**How to read:** §A current baseline · §B global guardrails (apply to *every* item) · §C reusable primitives (cited once, referenced everywhere) · §D the work, `W0`→`W12`, each with files/impl/edge-cases/tests/flag/done · §E sequencing · §F definition of done.

---

## A. Baseline — the starting line (already shipped)

Do **not** rebuild these (verified in code on this branch):
- **Security P0s:** inbound `scrub_secrets`, output `screen_output` firewall on the main chat, injection-defense system prompt.
- **Analytical layer:** F1 calibrated Safe-to-Spend (`forecast_changepoint.py` + split-conformal in `forecast_sim.py`, surfaced) — **live by default**; F2 merchant lifecycle (pooled BG/NBD via PyMC, `MerchantLifecycle` table) — **dark**; F3 nightly auditor (`audit_service.py`, `job_auditor` @ 00:50 UTC) — **dark**.
- **Multi-tenant foundation:** Postgres dialect-awareness, **RLS** (`db/rls.py`, `db/tenant.py`), DB-backed `LlmUsage` budget, `AgentConversationCache` seam, structured logging, UTC-pinned cron.

Partial / deferred: real scheduler leader election (static `scheduler_leader` gate only); Redis conversation store (seam only).

---

## B. Global guardrails (apply to EVERY work item)

1. **RLS tenant context (load-bearing).** RLS fails closed — a session with no tenant set returns **zero rows**. Any new code path that touches user data must establish context:
   - **Request path:** already handled by the `get_tenant_db()` dependency. Use it for new routers.
   - **Background jobs (W4, W6, behavioral jobs):** either (a) run under `settings.scheduler_database_url` pointing at a **BYPASSRLS** role (the `job_auditor` pattern — `_run_in_own_session` + iterate `_users(db)` + call services per `user.id`), or (b) if using the app `SessionLocal`, per user call `user_id_var.set(str(user.id))` **and** `set_tenant(db, user.id)` before querying. **Default to (a) for new nightly jobs.**
2. **Propose→confirm→verify only.** No new code moves money autonomously. All writes that affect money go through `ActionService.make_token` → `/assistant/actions/confirm/` → `ActionService.execute` (§C2), or the `allocate`-under-threshold earmark (§C1).
3. **Deterministic engine is authority; the LLM only narrates.** Every number shown is recomputed by code (Chronicler law). The output firewall blocks product/allocation/tax-filing advice — never route a new LLM surface around it.
4. **Ship dark.** Every new capability behind a `*_enabled` flag in `settings.py`, default `False`, flipped only after tests + a manual pass.
5. **Seeded determinism + backtest-before-ship** for any forecast/stat change (fixed-seed `random.Random`; `server/scripts/forecast_backtest.py`).
6. **Money is integer cents end-to-end**; convert to dollars only at the read/API seam (`cents_to_dollars`).
7. **Tests green after every PR:** `./.venv/bin/pytest -q`; run RLS-touching changes against Postgres (`test_rls_*`); `npm run test -- --run` for client.

---

## C. Reusable primitives (cited once)

- **C1 — Rules `allocate` earmark.** `rule_engine.py`: `action_params` JSON keys `"amount"` (dollars) **or** `"pct"` (0–100); target via `target_kind="goal"` + `target_id`. At/under `User.auto_execute_threshold_cents` (default `10000`=$100) it earmarks `Goal.progress` silently; above it calls `_propose_funding()` which writes a `Notification(type="rule_proposal", ref="rule_proposal:{rule}:{goal}:{cents}")` and the confirm token is **re-minted on demand** (never stored).
- **C2 — Action-token confirm flow.** `ActionService.make_token(user_id, action, params) -> jwt` · `/assistant/actions/confirm/` decodes, checks `is_token_used(jti)` (409 on replay), `mark_token_used`, then `ActionService.execute(db, user_id, action, params) -> dict`. `create_rule` is an existing executable action (validates shape DB-free, persists `RuleORM`).
- **C3 — Idempotent notifications.** `NotificationService._add_if_new(user_id, *, type, title, message, ref) -> Notification|None` — dedups by stable `ref` (read or unread). Existing `type`s: `budget_overrun`, `anomaly`, `rule_proposal`, `rule`, `bridge_nudge`.
- **C4 — Nightly job pattern.** `scheduler.py`: write a pure `job_x(db, now=None) -> dict`, an async `_x_tick()` via `_run_in_own_session`, register in `build_scheduler()` with `CronTrigger(timezone="UTC", ...)`, `replace_existing=True`, `misfire_grace_time=3600`, `coalesce=True`. Iterate users via `_users(db)`. **Obey guardrail B1.**
- **C5 — Long-term memory.** `user_memory.set_user_fact(db, user_id, key, value, *, source, confidence=100, pinned=False)` (trusted/deterministic lane, PII-scrubbed) · `propose_llm_fact(...)` (untrusted, firewall-gated) · `render_memory()` (2000-char budget). `MEMORY_KEYS` is a closed frozenset — extend it to add a key (code-only, no migration).
- **C6 — Assisted-action reconcile.** `assisted_action_service.reconcile(user_id, synced_txns, *, window_days=5, today=None) -> list[verified]`; matches an **appearing** signed transaction by exact magnitude + account + date window; `plaid_service._reconcile_bridges()` calls it and **discards the return**.
- **C7 — Conversation seam.** `AgentConversationCache` in `assistant_service.py` is the only call site for per-user executor+memory; its docstring anticipates a multi-key/shared-memory future.

---

## D. The work

> Effort key: S ≈ days · M ≈ 1–2 wk · L ≈ 3–4 wk · XL ≈ quarter+. Each item lists Goal · Files · Impl · Edge cases · Tests · Flag · Done.

---

### W0 — Validate & flip the dark analytical flags · *S* · no new code
**Goal:** turn on the already-built F2/F3 once trustworthy.
**Impl:** run `server/scripts/forecast_backtest.py <seed>` (confirm coverage ≈ doc'd 0.83 post-conformal); seed ≥5 repeat merchants + sanity-check `merchant_lifecycle_service.refresh()` flags zombies not healthy monthlies; in a staging env set `merchant_lifecycle_enabled=True` then `auditor_enabled=True`.
**Edge cases:** cold start (<5 merchants → `_MIN_MERCHANTS_FOR_FIT` self-skips; assert no crash, no notifications); auditor alert-fatigue (cap `auditor_max_findings=8` holds); a user with zero transactions (auditor emits nothing).
**Tests:** existing `test_merchant_lifecycle.py`, `test_audit_service.py` green with flags on; add a cold-start case asserting graceful skip.
**Done:** both flags on in staging for ≥1 nightly cycle with sane notifications; then enable in prod config.

---

### W1 — Mode-gating tool-router · *M* · flag `assistant_router_enabled`
**Goal:** deterministic per-turn tool-subset selection — cost, safety surface, headroom. (Full spec: `PLAN-router-and-feedback-loop.md` Feature 1.)
**Files:** new `services/assistant_router.py`; edit `services/assistant_service.py`, `settings.py`.
**Impl:**
- `assistant_router.py`: mirror `game/firewall.py` (import `normalize_for_matching`; compiled families `_MONEY`, `_WEB`, `_TAX_ORGANIZE`). `classify_mode(text, *, tax_enabled) -> (frozenset[str], mode_signature:str)`. Base `READ` always; `MONEY` standing core; add `WEB`/`TAX` on match. Lexicons per the plan doc.
- Build the tool list by filtering the registry to selected groups; key the executor cache by `(user_id, mode_signature)`.
- **Critical (seam integration, supersedes the plan doc's sketch):** to avoid each `(user,mode)` executor owning a *separate* `ConversationBufferWindowMemory`, store **one memory per user** and attach the same instance to every mode-executor for that user. Implement this *inside* `AgentConversationCache` (C7) — add a per-user memory map there, since it is the sanctioned seam (don't reintroduce a parallel `self.agents`/`self.memories` on the service). On multi-worker, the seam's history store is what gets externalized.
- Trim the system prompt to the active mode (write/rules/what-if/assisted-action paragraphs only when `MONEY`; tax paragraph only when `TAX`); **always** keep the security + no-advice paragraphs.
**Edge cases:** ambiguous/multi-intent → union (worst case = today's full set); mode switch mid-conversation must preserve history (shared memory); firewall short-circuits (crisis/dispute/tax-advice) still run **before** the router; `recategorize` invalidation must clear **all** `(user,*)` mode entries; flag off → full toolset (today's behavior).
**Tests:** new `test_assistant_router.py` (prompt→group set; union; WEB/TAX gated; TAX hidden when flag off even on tax intent); extend `test_assistant_invalidation.py` (invalidate clears all modes; read→money turn keeps continuity).
**Done:** with flag on, a data question binds only READ+MONEY; a "look up X" binds WEB; continuity holds across modes; suites green.

---

### W2 — "Cite sources" frame (verifiable AI) · *S* · no flag (additive)
**Goal:** make the anti-hallucination architecture visible — the #1 AI-distrust lever.
**Files:** edit `services/assistant_service.py` (streaming loop), `routers/assistant.py` (`_sse`), client chat renderer + `client/src/types`.
**Impl:** in the `astream_events` loop that already emits `tool` frames, capture the row ids/titles a read tool returned for the current turn; when the turn completes, emit a `sources` SSE frame `{event:"sources", data:[{id,title,date,amount}]}`. Scrub via the existing `_safe_for_llm`/PII rules; cap count.
**Edge cases:** no tool call (pure chat) → no sources frame; capped/`_truncated` tool output → label "based on N of M"; multiple tools → merge sources; never emit raw account numbers (PII scrub).
**Tests:** extend `test_assistant_frames.py` — a numeric answer emits a `sources` frame with scrubbed rows; a no-tool answer emits none.
**Done:** client shows "based on these N transactions" under figures.

---

### W3 — Self-host / no-egress profile · *S–M* · flag `egress_disabled`
**Goal:** a privacy SKU — "your data never leaves your machine."
**Files:** `settings.py`; `services/assistant_service.py` (tool registry); a `docker-compose.selfhost.yml` + README recipe.
**Impl:** `egress_disabled: bool = False`. When True, drop `WebSearchTool`/`OpenWebsiteTool`/`InformationTool` from every mode (reuse W1's group filter), and assert no outbound HTTP from assistant paths. Self-host recipe runs SQLite (existing) + locally-provided keys; document that Groq/Tavily are the only egress and how to disable them.
**Edge cases:** with egress off, the router never adds WEB even on web intent; the Clerk must say "web lookups are disabled" rather than silently failing; receipt/tax vision calls (Groq) are separately gated — document that "fully local" requires disabling those too (or a local model), don't over-claim.
**Tests:** new `test_egress_profile.py` — with `egress_disabled`, web tools absent from all modes; an assertion that no `requests`/socket egress occurs on a chat turn.
**Done:** a documented profile boots with zero outbound network from the assistant.

---

### W4 — Reconciliation→planning feedback loop · *M* · flag `assistant_reflection_enabled`
**Goal:** learn from outcomes — synthesize follow-through into one fact + offer to automate repeated verified actions (the Cleo-style gap, propose-only). (Spec: `PLAN-router-and-feedback-loop.md` Feature 2, **plus the RLS addendum below**.)
**Files:** new `services/action_reflection.py`; edit `user_memory.py` (`MEMORY_KEYS`), `scheduler.py`, `settings.py`.
**Impl:**
- `aggregate_outcomes(db, user_id, window_days)` → per-`kind` counts (proposed/verified/dismissed/expired), follow-through rate, median latency (`created_at`→`resolved_at`) from `AssistedAction` rows.
- `synthesize_fact(stats) -> str|None` → one short non-directive sentence; write via `set_user_fact(..., source="deterministic")` under a new key `"action_followthrough"` (add to `MEMORY_KEYS`, C5). After writing, invalidate the user's cached agent(s) so the Clerk picks it up.
- `detect_automatable(db, user_id, window_days, min_repeats)` → a (kind, goal/dest, ~amount) verified ≥ `reflection_min_repeats` on a regular cadence, with no equivalent `Rule`. For each, mint a one-tap rule offer reusing C1/C2/C3: a `Notification(type="rule_proposal", ref="rule_suggest:{kind}:{dest_or_goal}:{period}")`; on tap, mint a `create_rule` token (C2) for an `allocate` rule.
- `job_action_reflection(db, now)` nightly via C4. **RLS (B1):** run under the BYPASSRLS scheduler role, or `set_tenant(db, user.id)` + `user_id_var.set(...)` per user.
- Settings: `assistant_reflection_enabled=False`, `reflection_window_days=90`, `reflection_min_repeats=3`.
**Edge cases:** sparse history → `synthesize_fact` returns None (no fact written); fact must be factual/non-directive (run through `screen_output`, drop if blocked); suggestion suppressed if the user dismissed it before (check an existing dismissal marker / prior `ref`); a rule already covering the pattern → skip; the 2000-char memory budget — keep to one key, upsert; **RLS misconfig → zero rows → silent no-op (the classic trap; assert tenant context in a test).**
**Tests:** new `test_action_reflection.py` — aggregation math; fact upsert + firewall pass; offer fires only at ≥`min_repeats`, idempotent (one notification), skips when a `Rule` exists, respects flag-off + dismissal; job re-run no-op; **a Postgres test asserting the job sets tenant context and actually reads rows.**
**Done:** seeded 3× verified goal-funding → one fact + one rule offer; confirming the offer creates the `allocate` rule; nothing auto-moves money.

---

### W5 — Freelancer wedge ★ · *M* · flag `freelancer_mode_enabled`
**Goal:** the sharpest market play — "what's safe to spend *and* what to set aside for the IRS" for 1099 income. Composes shipped F1 calibrated S2S + the tax layer.
**Files:** migration `add_income_source_type`; edit `db/models.py` (Income), `services/categorization_service.py` (classifier), new `services/income_smoothing.py`, edit `services/onboarding`/a new `services/freelancer_setup.py`, `settings.py`.
**Impl:**
- **Income classification (MUST-ADD — confirmed no field exists).** Add `Income.source_type: Mapped[Optional[str]]` (`'w2' | 'self_employment' | 'other'`, nullable) + Alembic migration (default NULL; backfill heuristic from `category`/title keywords). User-overridable. Smoothing & reserve act **only** on `self_employment`.
- **`income_smoothing.py` (pure, seeded).** Compute monthly self-employment income dispersion over a trailing window; recommend an `s2s_buffer` (cents) covering a target-percentile low month (reuse the bootstrap-residual idea from `forecast_sim`). Returns a recommendation; applying it writes `User.s2s_buffer` (existing column) — surfaced as a one-tap accept, not auto-applied.
- **Tax reserve = a `Goal`** (recommended over Liability/new table — ties to existing earmark/allocate/Bridge machinery). Create a system Goal "Tax Reserve"; target = `tax_summary.annual_estimate_cents` (or `safe_harbor_annual_cents`). Fund it with a C1 `allocate` rule: condition `type == income` (+ `source_type == self_employment` once the classifier lands), `pct` = effective SE+income rate from the tax summary. Above-threshold fundings propose (C1); the existing `job_tax_quarterly_reminder` already closes the loop with due dates.
- **`freelancer_setup.py` onboarding preset** (one transactional bootstrap): set `s2s_horizon`, enable `tax_features_enabled`, create the Tax Reserve goal + the allocate rule, enable subscription detection, run an initial `income_smoothing` recommendation.
**Edge cases:** mixed W-2 + 1099 user (reserve/smoothing only on `self_employment` — never reserve on W-2 paychecks); a thin/zero income month (buffer draws down, reserve rule simply doesn't fire); the allocate rule must **not** match expenses (require the income condition — C2 validate already rejects condition-less allocate); reserve over-funding past the estimate (cap at goal target / mark complete); tax features disabled mid-stream (preset must no-op tax steps gracefully); migration backfill must not misclassify (default to NULL/`other`, never guess `self_employment`).
**Tests:** new `test_income_smoothing.py` (volatility→buffer determinism on seeded series; flat income → ~0 buffer); `test_freelancer_setup.py` (preset is idempotent, creates exactly one goal + one rule, no-ops when tax disabled); a rule test asserting the reserve rule fires on self-employment income only.
**Done:** a freelancer onboarding produces a calibrated Safe-to-Spend, a funded-as-income-arrives Tax Reserve, and quarterly due-date reminders — all propose-only.

---

### W6 — Honest subscription cancellation · *M* · flag `subscription_actions_enabled`
**Goal:** detect → offer cancel → verify it stopped, **no cut of savings** — inverting the most-complained automation in the category. Backed by the shipped F2 lifecycle.
**Files:** edit `db/models.py` (`AssistedAction.kind`), `services/assisted_action_service.py` (absence verification), new `services/subscription_actions.py`, `scheduler.py`, `settings.py`.
**Impl:**
- New assisted-action `kind="subscription_cancel"`; `how_json` carries the cancellation affordance (provider cancel URL / steps / deep link). It **proposes**; it never acts.
- **Detect→offer job** (`subscription_actions.py`, nightly via C4, RLS per B1): over `MerchantLifecycle` rows, flag candidates — `status in ("lapsing","dormant")` with low `probability_alive` (likely-forgotten) or positive `price_change_pct` (silent hike). For each, one idempotent `Notification(type="subscription_cancel", ref="sub_cancel:{user}:{merchant}:{period}")` offering a one-tap cancel **bridge** (mint the bridge on tap via C2).
- **Absence-based verification (new — C6 only matches *appearing* txns).** Add `verify_cancellation(bridge, as_of)` to `assisted_action_service`: a `subscription_cancel` bridge → `verified` when the merchant's expected next charge date (`MerchantLifecycle.expected_next_date` / cadence) plus a grace window passes with **no** matching charge at that merchant key. Run this in the nightly job (absence is only knowable over time), not the sync hook.
**Edge cases:** charge reappears under a slightly different merchant key/amount → require absence at the *normalized* merchant key for one full cadence + grace before verifying (avoid false "cancelled"); user re-subscribes later (bridge already resolved — a *new* cycle starts a fresh detection, not a re-open); annual subscription (long cadence → long verify horizon; cap how long a cancel bridge stays open, then expire with a nudge); a merchant that was already cancelled by the user before the offer (offer is dismissible; absence-verify still resolves it cleanly); never charge a fee — assert no fee field anywhere on this path.
**Tests:** new `test_subscription_actions.py` — offer fires only for zombie/price-creep candidates, idempotent per `ref`, respects flag-off; `verify_cancellation` marks verified only after a full missed cadence + grace, not on a one-cycle gap; a reappearing charge keeps it unverified; annual-cadence bridge expires rather than hanging forever.
**Done:** a forgotten sub surfaces one honest cancel offer; tapping creates a propose-only bridge; the next cycle's absence verifies it; zero fees.

---

### W7 — Behavioral features (Tier-1, evidence-graded) · *M* · per-feature flags
**Goal:** the behaviorally-validated nudges from `behavioral-moat.md`, each **forecast-gated** so a nudge can never push a user negative.
**Files:** edit `rule_engine.py` (escalation), `services/notification_service.py` (goal-named, landmark), new `services/behavioral.py`, `scheduler.py`, `settings.py`.
**Impl (build only the evidence-backed four):**
- **Goal-named reminders (F1).** Notifications that name the actual goal + progress; cadence-capped (≤1–2/wk); reuse C3.
- **Save-More-Tomorrow escalation (F2).** An opt-in `allocate` rule whose `pct`/`amount` auto-increments on a schedule. Rules don't self-escalate today → add a small monthly escalation step (a job that bumps `action_params` by the configured increment) **gated by the forecast**: skip the bump if `forecast.project_cashflows`/`will_go_negative` shows it would push negative. Trivially pausable.
- **Soft goal earmarks (F4).** Visible named sub-bucket per goal over `Goal.progress`; **never a hard lock**, instantly reversible; warn (don't block) if the forecast sees a near-term bill.
- **Landmark re-entry (F6).** Gentle re-entry notification at month/year boundaries **for lapsed users only**; skip engaged users (never reset streaks — `daily.py` already rebuilds rather than breaks).
**Edge cases:** escalation into deficit (forecast veto — hard requirement); reminder fatigue (cap + user mute → suppress winners); earmark over-restriction (always allow pull-back, no penalty); landmark licensing for on-track users ("what-the-hell" effect — target lapsed only); all copy non-directive, no shame (firewall).
**Tests:** new `test_behavioral.py` — escalation skips when forecast goes negative; reminders respect cadence cap + mute; earmark is always reversible; landmark targets lapsed, not engaged users.
**Done:** each feature flag-gated, forecast-vetoed, and measured against a holdout (north-star: "did the user act on a hard day?" — not DAU).

---

### W8 — Neurodivergent mode · *M* · flag `neurodivergent_mode`
**Goal:** position the real strength (no-break streaks + grace + no-shame) for an underserved segment.
**Files:** new `services/next_action.py` + `GET /next-action/` router; edit `game/grace.py` params, `settings.py`; client single-action surface + visual jars.
**Impl:**
- **"One thing today" (MUST-ADD — no unified next-action today).** `next_action.py` aggregates and ranks a single recommended action from: an open assisted-action **bridge due**, a pending **`rule_proposal`** to confirm, an **active challenge** ending soon (`ChallengeService.active`), **streak recovery** (`daily.py`), the top **auditor** finding. Return `{action_type, entity_id, copy}`. New `GET /next-action/`.
- **`neurodivergent_mode` profile:** widen `grace.py` generosity, lower reminder frequency/noise, default the client to the single-action surface.
- **Visual jars (client):** render `Goal.progress` sub-buckets as visible partitions (reuses W7 F4).
**Edge cases:** nothing actionable → a calm "you're all set" (never invent a task); multiple high-priority items → strict ranking, show exactly one; mode off → endpoint still works but UI doesn't default to it; grace widening must not disable challenge verdicts entirely (soft-land, not void).
**Tests:** new `test_next_action.py` — ranking picks the single highest-value action; empty state returns "all set"; grace params respected under the flag.
**Done:** with the flag on, the home surface shows exactly one next action and the experience never shames a lapse.

---

### W9 — UI / assessment residuals · *M*
**Goal:** close the audit's honest disconnects; make W4/W5/W7 rules user-manageable.
**Files:** client pages + the relevant routers.
**Impl:**
- **Rule-creation/management UI** (pull earlier if W4/W5/W7 land first — they create rules the user must see/edit/pause). Backend CRUD exists; build the surface.
- **MCP-key management UI** (CRUD exists server-side at `/api/mcp-keys/`; the agent story is unreachable without it).
- **Wire the Homestead commit action** (server prepares the payload; client `onClick` missing).
- **Plaid-overwrites-manual-edits guard** (`plaid_service._process_modified`): preserve user-edited fields or warn in UI. *ASSESSMENT P1 #6.*
- **Assert `typ` on the access path** (`auth_service.get_current_user`): reject a non-empty `typ` (defense-in-depth). *ASSESSMENT P2 #10.*
**Edge cases:** a rule the user pauses must stop firing immediately (invalidate caches); Plaid guard must not block legitimate Plaid corrections (warn + let user choose source of truth); `typ` assertion must not break existing access tokens (they carry `sub`, empty `typ`).
**Tests:** client tests for each surface; a backend test that a `typ`-bearing token is rejected on the access path; a Plaid-resync test asserting an edited field is preserved/warned.
**Done:** the agent + rules + Homestead stories are reachable from the UI; the two security residuals closed.

---

### W10 — Productization foundation completion · *M* · trigger: >1 worker
**Goal:** finish the multi-worker seams the foundation left static.
**Impl:** real scheduler **leader election** via `pg_try_advisory_lock` (replace the static `scheduler_leader` gate; resolves the remainder of ASSESSMENT P1 #5); **Redis conversation store** behind the C7 seam (`RATELIMIT_STORAGE_URI=redis://`, history-only). *Source: MULTI-TENANT-DEFERRED #1.*
**Edge cases:** leader failover (lock release on crash — advisory locks auto-release on connection drop); split-brain double-jobs (idempotent jobs already tolerate it, but the lock prevents waste).
**Tests:** a leader-election test (two schedulers, one runs); a Redis-store round-trip test.
**Done:** N app replicas run with exactly one scheduler and shared conversation history.

---

### W11 — Couples / household · *XL* · trigger: validated demand
**Goal:** the one genuine "behind" gap. **Validate demand first** (unconfirmed in research).
**Impl (green-field, foundation now exists):** a `Household`/membership + permission model; thread a household scope through the financial tables **and** the game projections (the game layer is global/single-user — `game/__init__.py` warns against partial changes); per-user privacy controls on shared accounts; **requires** MFA + field-encryption (W12). RLS policies extend from `user_id` to `(user_id OR household member with grant)`.
**Edge cases:** split-brain game projections (must scope per-household atomically, not partially); a member leaving a household (data ownership + revocation); per-account visibility (one partner hides an account); RLS policy correctness under the new predicate (cross-household leak test).
**Tests:** a full cross-household isolation suite (extend `test_rls_*`); game-projection-per-household integrity; revocation purges access.
**Done:** two users share a household with correct, RLS-enforced, per-account privacy and no game split-brain.

---

### W12 — Compliance & deferred bolts · *L–XL* · trigger: real users / scale
**Goal:** everything required to hold other people's money/data and to scale.
**Impl (each at its trigger, from MULTI-TENANT-DEFERRED + ASSESSMENT §6):** GLBA / FTC Safeguards program + Plaid production access; field-level KMS encryption (tokens/identifiers) + immutable audit + account-deletion erasure (purges derived stores: chunks, embeddings, cache, conversation history); MFA/lifecycle (TOTP/WebAuthn, reset, verification, lockout); per-user timezone (`user.timezone` + `today_for(user)`, ~8 boundary sites); Plaid-scale queue+worker; pgvector hybrid RAG; observability (Sentry/OTel/LangSmith); stateless multi-instance + PgBouncer; partitioning/replicas only on **measured** load.
**Edge cases:** erasure must reach **every** derived store (the silent-leak risk); per-user timezone must not break existing date-only buckets (the audit confirmed they're safe — change only the "today" seam).
**Tests:** an erasure test asserting all derived rows are gone; per-timezone day-boundary tests; RLS + encryption interaction tests.
**Done:** the GLBA checklist is satisfied, Plaid prod is live, and a deletion request provably purges everything.

---

## E. Sequencing & critical path

```
W0 (flip analytics, S)
   │
W1 router ── W2 cite-sources ── W3 self-host           (R1, parallelizable, 1–2 wk)
   │
W4 feedback loop ─┐
W5 Freelancer ★  ─┤  (R2 — W5 is the payoff; all unblocked by shipped F1/F2)   3–5 wk
W6 Honest-subs   ─┤
W7 behavioral    ─┘
   │
W8 neurodivergent  (R3, needs game + W7)               1–2 wk
   │
W9 UI/residuals    (R4; pull rule-UI earlier if W4/W5/W7 land first)  1–2 wk
   │
W10 leader/Redis ── W11 couples ── W12 compliance      (R5, each at its trigger)
```

**Recommended path:** `W0 → W1 → W5` (router then straight to the Freelancer wedge — the market-advantage payoff), interleaving `W2/W4/W6/W7` as capacity allows. `W9`'s rule-UI should be pulled forward the moment W4/W5/W7 create user-facing rules. `W10–W12` are gated by real-user/scale triggers, not feature priority.

---

## F. Definition of "app complete"

The app is **product-complete for a single-user / self-host launch** when W0–W9 are merged behind validated flags, both suites green (backend on Postgres), and:
- the Freelancer wedge (W5) is end-to-end (calibrated S2S + tax reserve + quarterly reminders),
- the assistant is router-gated (W1) with visible sources (W2) and an optional no-egress profile (W3),
- the feedback loop (W4), honest-subscription (W6), behavioral (W7), and neurodivergent (W8) features are live behind flags,
- the audit residuals (W9) are closed.

It is **multi-user / real-money launch-ready** when W10–W12 are satisfied: leader election + shared state (W10), validated household model (W11), and the GLBA/Plaid-prod/encryption/erasure/MFA compliance set (W12). Until then it stays explicitly single-user by design.

**Every step obeys §B. No exceptions — especially B1 (RLS) for the new nightly jobs in W4/W6/W7.**
