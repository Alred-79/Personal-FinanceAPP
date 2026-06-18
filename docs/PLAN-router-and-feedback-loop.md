# Plan: Mode-Gating Tool-Router + Reconciliation→Planning Feedback Loop

## Context

persFin's assistant is a **single LangChain tool-calling agent** (not multi-agent like Cleo). Two gaps surfaced when benchmarking against the agentic-finance industry:

1. **Tool growth pressure.** One agent now carries ~15–18 tools on every turn. Research (2025–26) shows tool-selection accuracy is fine up to ~50 tools but degrades sharply toward ~200, and that the cheap web tools (`search_web`/`open_website`) needlessly widen the SSRF/cost surface on turns that never need them. persFin is *below* the danger zone, so the right-sized fix is a **deterministic mode-gate** (not RAG-over-tools), reusing the existing firewall classifier pattern. Wins: lower per-turn token cost, smaller safety surface, and headroom as tools grow.

2. **No learning from outcomes.** `AssistedActionService.reconcile()` already verifies whether a *proposed* action actually happened against real Plaid data — but the verified-bridge return value is **discarded** at `services/plaid_service.py:380`, and there is **no adaptive planning state** anywhere. This is exactly the "continuous learning from observed outcomes" capability Cleo markets. Closing it — while staying propose-only — is persFin's highest-leverage differentiator, because it's the rare app already capturing the outcome data.

Research steer (applied below): the 2025–26 agent-memory literature (Memento 2 / SRDP, MemRL) warns that **raw episodic logs bloat without value** — the loop must *synthesize generalizable facts*, not accumulate events. So the feedback loop writes a small, regenerated summary, never an event log.

**Both features ship behind flags, dark by default**, matching the `tax_features_enabled` / `detangle_enabled` / `mcp_enabled` precedent.

---

# Feature 1 — Deterministic mode-gating tool-router

## Design

A per-turn deterministic classifier selects which **tool groups** the agent sees, mirroring the firewall's mechanism (Unicode-normalized text + compiled regex families, no LLM call). Groups are **additive**: a READ base is always present; MONEY is part of the standing core; TAX and WEB are gated in only when their intent fires. Worst case (ambiguous/multi-intent) = union of fired groups; nothing ever removes capability the user demonstrably needs.

**Tool groups** (from `services/assistant_service.py:2470-2497`):
- `READ` (always): `get_transactions_by_date_range`, `get_transactions_by_category`, `get_accounts`, `get_transactions_per_account`, `get_spend_details`, `get_goals`
- `MONEY` (standing core): `add_transaction`, `add_goal`, `recategorize_transaction`, `what_if`, `create_rule`, `propose_assisted_action`
- `WEB` (gated on intent): `search_web`, `open_website`, `get_information`
- `TAX` (gated on intent **and** `tax_features_enabled`): `tag_transaction_tax`, `get_tax_summary`, `get_deductions_by_bucket`

**Initial policy:** default mode = `READ + MONEY` (financial conversation stays fully capable; money false-negatives are costly so we don't gate writes yet). `WEB` added only on explicit look-up/search intent (also shrinks SSRF surface). `TAX` added only on tax-organize intent + flag. A stricter **pure-READ** mode (drop MONEY for unambiguous data questions) is deferred to a phase 2 after we measure classifier false-negatives — the machinery supports it from day one.

## Key subtlety — shared conversation memory across modes

Executors will be cached per `(user_id, mode)`, but `ConversationBufferWindowMemory` is currently built *inside* the executor, so naive per-mode executors would each get a **separate history buffer** and break continuity when a user crosses modes mid-conversation. **Fix:** hold one memory object per user in a new `self.memories` cache and attach the *same* instance to every mode-executor for that user. Memory resets only on explicit reset, never on mode switch.

## Changes

- **New** `Personal-FinanceAPP/server/src/services/assistant_router.py`
  - Mirror `services/game/firewall.py`: import `normalize_for_matching`; define compiled regex families `_MONEY`, `_WEB`, `_TAX_ORGANIZE`.
  - `classify_mode(text, *, tax_enabled) -> frozenset[str]` → set of group names (always includes `READ`,`MONEY`; adds `WEB`/`TAX` on match). Returns a stable `mode_signature` string (e.g. `"read+money+web"`).
  - Lexicons: MONEY = move/transfer/pay/save/set aside/fund/automate/rule/alert/add (a/an) transaction/recategorize/what if/raise. WEB = look up/search/google/what is the price/current/latest/news. TAX = deduct(only org-context)/schedule c/bucket/1099/1098/write-off/tax summary — note tax *advice* is already short-circuited by the firewall *before* the router runs, so this only catches organize/summarize intent.
- **Edit** `services/assistant_service.py`
  - Replace `self.agents: TTLCache[int, AgentExecutor]` (line ~2330) keyed by `user_id` with keying by `(user_id, mode_signature)`; bump `maxsize` (128 → 384) to hold ~6 combos/user.
  - Add `self.memories: TTLCache[int, ConversationBufferWindowMemory]` (per-user shared memory).
  - In `chat()` (after the firewall screens, ~line 2467): call `assistant_router.classify_mode(message, tax_enabled=...)`; build the tool list by filtering the registry to the selected groups; fetch-or-build the `(user, mode)` executor with the **shared** per-user memory attached.
  - Extract the system-prompt assembly (lines 2504-2559) into `build_system_prompt(mode, tax_enabled, memory_text)`: include the write-tools / rules / what-if / assisted-action paragraphs only when `MONEY` present, the tax paragraph only when `TAX` present; **always** keep the security + no-advice guardrail paragraphs and the learned-memory block.
  - Update `invalidate_agent(user_id)` (~line 2803) to pop **every** `(user_id, *)` key, not one entry: `for k in list(self.agents): if k[0]==user_id: self.agents.pop(k,None)`.
  - Optional observability: emit a `mode` SSE frame (event `"mode"`) when a debug setting is on. Low priority.
- **Edit** `services/settings.py` (`settings.py`): add `assistant_router_enabled: bool = False`. When False, `chat()` uses the full toolset (today's behavior) — instant kill switch.

## Tests
- **New** `Personal-FinanceAPP/server/tests/test_assistant_router.py` (pattern from `test_assistant_privacy_safety.py`): representative prompt → expected group set; additive union; WEB/TAX absent unless intent fires; TAX hidden when flag off even on tax intent; ambiguous → core READ+MONEY.
- Extend `test_assistant_invalidation.py`: invalidating a user clears all mode executors; mode switch preserves shared memory (continuity across a read→money turn).

---

# Feature 2 — Reconciliation→planning feedback loop (reflection + automation offers)

## Design

A nightly job reads each user's `AssistedAction` rows (which already persist `kind`, `status`, `created_at`, `resolved_at`, `amount_cents`, `dest_ref`/`how_json.goal_id`), aggregates follow-through over a trailing window, and produces two outputs:

1. **Reflection memory (Tier 1).** One *regenerated, generalized* fact per user — e.g. "Acts on goal-funding within ~2 days; tends not to act on bill reminders." Written through `user_memory.set_user_fact(source="deterministic")` (PII-scrubbed, factual, non-directive). Injected into the Clerk's system prompt on next rebuild so future proposals adapt emphasis. One key, upserted each run → no episodic bloat (the research's "active compression" requirement).

2. **Automation offer (Tier 2).** When a stable pattern verifies repeatedly (same `kind` + goal/`dest_ref` + ~amount, ≥ N times on a regular cadence) and no equivalent `Rule` exists, surface **one** idempotent notification proposing a `create_rule` (`allocate`) automation — reusing the existing one-tap proposal machinery. The rule stays **propose-only**; the user confirms via the normal `/assistant/actions/confirm/` flow. Nothing auto-fires — the trust model is preserved.

**No new tables.** All inputs already live on `AssistedAction`; outputs go to `user_memory` (new keys, code-only) and `Notification` + an action token (both existing).

## Changes

- **New** `Personal-FinanceAPP/server/src/services/action_reflection.py` (pure logic, like `detangle_service.py`):
  - `aggregate_outcomes(db, user_id, window_days)` → per-`kind` counts (proposed/verified/dismissed/expired), follow-through rate = verified/(verified+dismissed+expired), median latency for verified (from `created_at`→`resolved_at`).
  - `synthesize_fact(stats) -> str|None` → one short non-directive sentence; `None` if too little data.
  - `detect_automatable(db, user_id, window_days, min_repeats)` → patterns eligible for a rule offer.
  - `run_for_user(db, user_id, *, now)` → writes the fact via `set_user_fact`, fires ≤1 idempotent rule-suggestion notification, returns a summary dict. Calls `invalidate_agent(user_id)` after a fact change so the Clerk picks it up promptly.
- **Edit** `services/user_memory.py`: add `"action_followthrough"` (and optionally `"goal_affinity"`) to `MEMORY_KEYS` (frozenset, ~line 42) — **code-only, no migration** (`UserMemory.key` is already a free String). Keep to one or two keys to respect the 2000-char render budget.
- **Reuse for the automation offer** the existing one-tap proposal pattern in `services/rule_engine.py:260-279` (mints an action token + a `Notification`); dedup by `ref = f"rule_suggest:{kind}:{dest_or_goal}:{period}"`. Screen the suggestion text through `firewall.screen_output` (same as rationale screening) and respect a dismissal/suppression marker so a declined offer doesn't re-surface.
- **Edit** `services/scheduler.py`: add `job_action_reflection(db, now)` (idempotent, per-user, gated by the flag), an async `_reflection_tick`, and registration in `build_scheduler()` following the `detangle` pattern (lines ~339-344): `CronTrigger(hour=1, minute=0)`, `id="action_reflection"`, `replace_existing=True`, `misfire_grace_time=3600`, `coalesce=True`. Honor the single-worker invariant.
- **Edit** `settings.py`: add `assistant_reflection_enabled: bool = False`, `reflection_window_days: int = 90`, `reflection_min_repeats: int = 3`.

## Tests
- **New** `Personal-FinanceAPP/server/tests/test_action_reflection.py` (patterns from `test_assisted_action.py` + `test_game_scheduler.py`): aggregation math from synthetic `AssistedAction` rows; fact synthesis upserts one key and **passes the firewall** (non-directive); automation offer fires only at ≥`min_repeats` verified, is idempotent (one notification), skips when an equivalent `Rule` exists, respects flag-off and dismissal; job re-run is a no-op; `invalidate_agent` called after a fact write.

---

## How the two features interact
Independent for v1. The automation offer confirms via a MONEY-group action (`create_rule`) — orthogonal to the router. Later, reflection facts could *also* inform the router (e.g. de-prioritize MONEY for users who never act) — out of scope now.

## Rollout
Both flags default **False**. Flip `assistant_router_enabled` after the classifier suite + a manual prompt-sweep confirm no MONEY/TAX false-negatives. Flip `assistant_reflection_enabled` after verifying fact quality and suggestion idempotency on seeded data.

## Verification (end-to-end)
- **Tests:** from `Personal-FinanceAPP/`, run `./.venv/bin/pytest -q` (no pipenv) — new suites plus existing `test_assistant_*`, `test_assisted_action.py`, `test_game_scheduler.py`, `test_user_memory.py` to confirm no regression.
- **Router (manual, flag on):** `POST /assistant/chat/` with (a) "how much did I spend on groceries last month" → only READ+MONEY tools bound; (b) "look up the current price of gold" → WEB tools present; (c) a tax-organize query with `tax_features_enabled` on/off → TAX present/absent. Verify via the optional `mode` SSE frame or a debug log; confirm a read→money→back conversation keeps continuity (shared memory).
- **Feedback loop (manual, flag on):** seed 3 verified goal-funding `AssistedAction` rows to one goal; run `job_action_reflection` (call the pure function or trigger the tick); assert (1) a `user_memory` `action_followthrough` fact appears and renders into the prompt, and (2) one rule-suggestion `Notification` with an action token exists; confirm the token via `/assistant/actions/confirm/` and assert a `Rule` (allocate) is created and nothing auto-moved money. Re-run the job → no duplicate notification.
- Note the scheduler **single-worker invariant** when validating job behavior.

---

## Appendix — industry benchmark sources

Agentic-finance landscape and trend research backing this plan:
- Cleo Autopilot multi-agent architecture (router + specialized sub-agents, structured handoffs, continuous learning) — meetcleo.com/blog/introducing-autopilot
- Tool-count accuracy degradation / dynamic tool loading — arXiv 2509.20386 (Dynamic ReAct); vllm-semantic-router.com/blog/semantic-tool-selection
- Agent memory / reflection / "active compression" of episodic outcomes — arXiv 2512.22716 (Memento 2 / SRDP); arXiv 2601.03192 (MemRL)
- Industry posture: most consumer apps read-only (Monarch, Ghostfolio, OSS); Cleo/Erica execute; trust barrier (~18% trust AI for financial decisions, TD survey); IMF/Hogan Lovells on authorization/explainability barriers.
