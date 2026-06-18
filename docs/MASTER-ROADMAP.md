# persFin — Master Roadmap

**Date:** 2026-06-18 · **Branch of record:** `feature/analytical-layer` (ahead of `main`; the new strategy docs are still untracked)
**What this is:** the single ordered plan that sequences every proposed change across the docs by **dependency**. Read this to know *what's left, in what order, and why*.

> **Updated after a code re-check (2026-06-18).** A large slice of the original roadmap **already shipped** on `feature/analytical-layer` — the entire analytical layer (Phase 2) and the entire multi-tenant foundation (Phase 6). The "what's left" below is the real remaining work. A new live constraint (RLS) now governs how all remaining background jobs must be written — see §4.

**Source docs consolidated here:** `MARKET-OPPORTUNITY.md`, `PLAN-router-and-feedback-loop.md`, `ANALYTICAL-LAYER-ROADMAP.md`, `FORECAST-BACKTEST.md`, `behavioral-moat.md`, `MULTI-TENANT-DO-NOW.md`, `MULTI-TENANT-DEFERRED.md`, `TIMEZONE-AUDIT.md`, `ASSESSMENT.md`.

---

## 0. Status ledger — what is already shipped on this branch

Verified against code, not commit messages.

### ✅ DONE
| Area | What landed | Evidence | Flag / default |
|------|-------------|----------|----------------|
| **ASSESSMENT P0s** | Inbound `scrub_secrets`, firewall `screen_output` on main chat, injection-defense system prompt | `assistant_service.py` (scrub @ ~2512, screen @ ~2741, security prompt @ ~2570) | always-on |
| **Timezone fix** | All `CronTrigger`s pinned `timezone="UTC"`; half-open range convention documented | commit `8e9ef95` (WS4) | n/a |
| **Analytical F1 — calibrated S2S** | `forecast_changepoint.py` (CUSUM), split-conformal in `forecast_sim.py`, `trough_band`/`overdraft_probability`/`band_calibrated` surfaced in `SpendCard`/`Forecast` | commit `138778c` | `forecast_changepoint_enabled=True`, `forecast_coverage_level=0.90` — **live by default** |
| **Analytical F2 — merchant lifecycle** | Real pooled **BG/NBD via PyMC** (`merchant_lifecycle_service.py`), `MerchantLifecycle` table + migration, price-creep, surfaced on `Subscriptions` | commit `138778c` | `merchant_lifecycle_enabled=False` — **dark** |
| **Analytical F3 — nightly auditor** | `audit_service.py` composes anomaly/overrun/overdraft/lifecycle/price-creep → one screened Groq narration → idempotent notifications; `job_auditor` @ 00:50 UTC; also owns the nightly F2 fit | commit `138778c` | `auditor_enabled=False` — **dark** |
| **Multi-tenant WS1 — Postgres** | Dialect-aware engine (`db/types.py` JSONB/TEXT, `db/session.py`), migrations, docker-compose + roles; SQLite still works | commits `793db7c`,`8f945aa`,`675044e` | `DATABASE_URL` |
| **WS2 — RLS isolation** | `db/rls.py` `set_tenant()` = `SET LOCAL app.user_id`; `db/tenant.py` `get_tenant_db()` dep on every authed router; `TENANT_TABLES` (29+6 denormalized); RLS migrations + 3 test suites | commits `8f945aa`,`675044e` | `enable_rls` (PG only) |
| **WS3 — state seams** | `AgentConversationCache` seam, **DB-backed `LlmUsage`** budget (requests hard-capped, cost_cents enforced), static `scheduler_leader` gate | commit `6656ab3` | seams in place |
| **WS5 — structured logging** | `logging_context.py` (`request_id` + `user_id` in contextvars), JSON logs | commit `73a7d91` | n/a |

### 🟡 PARTIAL (seam exists, completion deferred)
- **Real scheduler leader election** — only a static `scheduler_leader` gate today; `pg_try_advisory_lock` election is backlog (needed before >1 worker). Resolves the remainder of ASSESSMENT P1 #5.
- **Conversation store for multi-worker** — `AgentConversationCache` is the seam; a Redis-backed history store is deferred (DEFERRED #1).

### Net effect on the old plan
- Old **Phase 0** (tz + P0 true-up): **DONE.**
- Old **Phase 2** (analytical layer): **DONE** (F1 live; F2/F3 ship dark — flip after validation).
- Old **Phase 6** (multi-tenant foundation): **DONE** except real leader election.
- The **foundation track is no longer a blocker** — multi-user/couples is now gated only on a household model + MFA/field-encryption + leader election, not a from-scratch retrofit.

---

## 1. The remaining dependency spine

```
   already shipped: P0 true-up · analytical F1/F2/F3 · Postgres+RLS+seams+logging
        │
   R1  router + cite-sources + self-host/no-egress      (assistant precision/trust)
        │   (router integrates the existing AgentConversationCache seam)
        ▼
   R2  feedback loop  +  Freelancer wedge  +  Honest-subscription  +  behavioral
        │   (F1 calibrated S2S → freelancer;  F2 zombies → honest-subs — BOTH now DONE,
        │    so these dependencies are already satisfied)
        ▼
   R3  Neurodivergent mode            (needs game + behavioral from R2)
        │
   R4  UI / assessment residuals      (rule-creation UI also makes R2 rules manageable)
        │
   R5  leader election → couples/household → DEFERRED bolts → GLBA/Plaid-prod compliance
            (each at its trigger; foundation already in place)
```

**Every new background job in R2 must obey the RLS rule in §4.**

---

## 2. Remaining phased plan

### R1 — Assistant precision + visible trust · *1–2 wks*
- **R1a. Mode-gating tool-router.** Deterministic classifier → READ/MONEY/TAX/WEB groups; cache executors per `(user, mode)` with **shared per-user memory**. *Integration note (new):* hook the existing `AgentConversationCache` seam rather than the old `self.agents` cache — store history once per user and attach it to each mode-executor (the seam already anticipates this; see its docstring). *Source: PLAN Feature 1. Flag: `assistant_router_enabled=False`. Effort: M.*
- **R1b. "Cite sources" frame.** Emit a `sources` SSE frame with the backing transaction rows when the Clerk states a number (scrubbed via `_safe_for_llm`). *Source: MARKET gap 2. Effort: S.*
- **R1c. Self-host / no-egress profile.** A settings profile that disables the outbound web tools (reuses R1a's WEB gating) + a one-command self-host recipe over the existing SQLite path. *Confirmed not present today.* *Source: MARKET gap 4. Effort: S–M.*
- **R1d. Position** human-in-loop + incentive-aligned — messaging, no build.

### R2 — The market wedges · *3–5 wks*
Their hardest dependencies (calibrated S2S, zombie detection) are **already shipped**, so this phase is now unblocked.
- **R2a. Reconciliation→planning feedback loop.** Nightly job → one generalized `user_memory` fact + idempotent one-tap automation offers. *Source: PLAN Feature 2. Flag: `assistant_reflection_enabled=False`. Effort: M.* **Must set RLS tenant context (§4).**
- **R2b. Freelancer wedge ★.** `income_smoothing.py` (volatility→`s2s_buffer`) + tax-reserve `allocate` rule + onboarding preset. Calibrated S2S (F1) is **already live**, so the forecast half is done. *Source: MARKET gap 5. Flag: `freelancer_mode_enabled`. Effort: M.*
- **R2c. Honest subscription cancellation.** New `subscription_cancel` assisted-action kind + detect→offer job (now backed by the **shipped F2 `MerchantLifecycle.probability_alive`/`price_change_pct`**) + absence-based verification. *Source: MARKET gap 7. Flag: `subscription_actions_enabled`. Effort: M.* (Smaller than before — F2 detection is done.) **Offer job must set RLS tenant context (§4).**
- **R2d. Behavioral features (Tier-1, forecast-gated).** Goal-named reminders, Save-More-Tomorrow escalation, soft earmarks, lapsed-only landmark re-entry — each vetoed by `project_cashflows` if it would push negative. *Source: behavioral-moat. Effort: M.*

### R3 — Neurodivergent mode · *1–2 wks*
"One thing today" surface + `neurodivergent_mode` profile (widen `grace.py`, quiet reminders) + optional visual jars. *Source: MARKET gap 6. Flag: `neurodivergent_mode`. Effort: M.*

### R4 — UI / assessment residuals · *1–2 wks*
- **Rule-creation UI** (also makes R2a/R2b/R2d rules user-manageable — consider pulling into R2), **MCP-key management UI**, **wire Homestead commit**. *ASSESSMENT §1 / P2.*
- **Plaid-overwrites-manual-edits guard** (P1 #6); **assert `typ` on access path** (P2 #10).

### R5 — Productization & deferred (each at its trigger)
- **Real scheduler leader election** (`pg_try_advisory_lock`) — before >1 worker.
- **Couples / household** — now gated only on a household/permission model threaded through tables + game projections, **plus** MFA + field-encryption. Foundation (Postgres/RLS) is done. **Validate demand first.** *MARKET §5 + DEFERRED #8–9.*
- **DEFERRED bolts** at their triggers: Redis conversation store, per-user timezone, Plaid-scale queue, pgvector RAG, observability, stateless multi-instance, partitioning, MFA/lifecycle, field encryption + audit + erasure. *MULTI-TENANT-DEFERRED.*
- **Compliance for real money** — GLBA / FTC Safeguards + Plaid production. *ASSESSMENT §6.*

---

## 3. Validate-before-building
Unconfirmed/refuted in the market research — run VoC before committing slots: explicit "will-I-make-it-to-payday" demand (refuted as too generic), couples/household demand strength, multi-currency/immigrant, net-worth+investment unification, students, sinking-funds specifics.

---

## 4. Guardrails for every remaining phase

**NEW — RLS tenant context (load-bearing; applies to all R2+ jobs/services).** RLS is live: a session with no tenant set returns **zero rows** (fails closed). Any new background job that iterates users must do one of:
- **Preferred:** run under `scheduler_database_url` pointing at a **BYPASSRLS** read/write role (the `job_auditor` pattern — `_run_in_own_session` + `_users(db)` then call services per `user.id`); **or**
- **If using the app `SessionLocal`:** per user, `user_id_var.set(str(user.id))` **and** `set_tenant(db, user.id)` (`db/rls.py`) before querying.

This changes the feedback-loop and subscription-offer jobs in the PLAN/MARKET docs, which were written pre-RLS — patch those specs when implementing.

**Unchanged invariants:**
- **Propose→confirm→verify only.** No phase moves money autonomously.
- **Deterministic engine is authority; LLM narrates.** Every number the LLM shows is recomputed by code; the firewall blocks product/allocation/tax-filing advice.
- **Ship dark.** New capability behind a `*_enabled` flag, default False, flipped after tests + a manual pass. (Note: F1 changepoint+conformal already ships **on**; F2/F3 are dark — flip after backtest/coverage validation.)
- **Seeded determinism + backtest-before-ship** for any forecast change.
- **Full suite green after every PR** (`./.venv/bin/pytest -q`; on Postgres for RLS-touching changes — see `test_rls_*`).

---

## 5. One-screen sequence (remaining only)

| Phase | Theme | Depends on | Effort |
|-------|-------|-----------|--------|
| ~~0,2,6~~ | ~~true-up · analytical layer · multi-tenant foundation~~ | — | **DONE** |
| R1 | Router · cite-sources · self-host | shipped seams | 1–2 wk |
| R2 | Feedback loop · **Freelancer** · Honest-subs · behavioral | F1+F2 (done) · §4 RLS | 3–5 wk |
| R3 | Neurodivergent mode | game + R2d | 1–2 wk |
| R4 | UI / assessment residuals | (rule UI aids R2) | 1–2 wk |
| R5 | leader election · couples · deferred · compliance | foundation (done) + triggers | per trigger |

**Start next:** flip-validate F2/F3 (they're built but dark — backtest coverage + a zombie-detection sanity pass, then enable), then **R1 router** and build toward the **Freelancer wedge (R2b)** as the first market-advantage payoff. Remember §4 for every new job.

---

## 6. First action items
1. **Validate & flip the dark analytical flags:** run `server/scripts/forecast_backtest.py`, sanity-check `merchant_lifecycle` on seeded payees, then enable `merchant_lifecycle_enabled` / `auditor_enabled` in a controlled env.
2. **Patch the PLAN & MARKET specs** for the §4 RLS constraint before implementing their nightly jobs.
3. **Commit the untracked strategy docs** (`MASTER-ROADMAP`, `MARKET-OPPORTUNITY`, `PLAN-router-and-feedback-loop`) so the plan of record is in git.
4. Begin **R1a router** against the `AgentConversationCache` seam.
