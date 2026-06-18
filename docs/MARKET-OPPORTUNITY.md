# persFin — Market Opportunity & Implementation Map

**Date:** 2026-06-18
**Purpose:** Rank the validated, unmet user-demand gaps in US consumer personal finance (2025–26) and map each to a concrete implementation path **using the code that already exists in this repo**. The recurring finding: persFin already sits on top of most of the validated white-spaces — the work is mostly *packaging and pointing*, with two genuine new builds.

> Sourcing note: demand signals below come from a verified deep-research pass (14 of 25 candidate claims were *killed* in adversarial verification, so only survivors are cited). Where a gap was named in the brief but its demand could not be verified, it is flagged as **unverified — validate first**.

---

## 0. Two corrections to earlier internal notes (ground-truth from code)

Both "unbuilt differentiators" from older memory are in fact **at least partially built** — which strengthens the wedges below:

- **Merchant-lifecycle / BG-NBD ("is this subscription still alive?")** EXISTS: `server/src/services/subscription_service.py` (`detect_subscriptions()`), surfaced via `GET /subscriptions/`, with an F2 enrichment behind `merchant_lifecycle_enabled` returning `probability_alive`, `lifecycle_status`, `price_change_pct`.
- **Conformal forecasting** EXISTS: `server/src/services/forecast_sim.py` carries a split-conformal (CQR) calibration path on top of the moving-block bootstrap.

Treat both as real assets when positioning.

---

## 1. The ranked opportunity table

| # | Gap | Demand signal (verified) | Served today | persFin leverage | Move | Effort |
|---|-----|--------------------------|--------------|------------------|------|--------|
| 1 | AI assists, human decides | 10%→55% AI-for-finance use in a yr; only **18%** trust AI to decide alone | Poorly (agentic apps push autonomy) | Propose→confirm→verify; never executes | Position | None (built) |
| 2 | Verifiable AI | Distrust of AI *info* = top non-use reason (31%) | Poorly (chatbots hallucinate) | LLM never emits numbers (deterministic fact sheet); actions reconciled | Position + "cite sources" | S |
| 3 | Incentive-aligned (no product-pushing) | Referral-steering distrust; CFPB/FTC actions | Structural conflict in free apps | Firewall blocks product/loan/investment recs | Position | None (built) |
| 4 | Privacy / no data-selling | 60% of budgeting apps share data; 71% would quit over it | Poorly | PII never reaches LLM; Fernet tokens; local SQLite | Position + self-host | S |
| 5 | **Freelancer / irregular income + taxes** | Real; need = budget money-on-hand + buffer; no app pairs it with taxes | Thin | Probabilistic S2S + Schedule-C tax + quarterly reminders | **Package (wedge)** | M |
| 6 | **ADHD / neurodivergent** | 47% of ADHD adults dissatisfied; only niche newcomers serve it | Almost unserved | Game layer: no-break streaks, grace, no-shame | **Tune & position** | M |
| 7 | **Honest subscription mgmt** | Rocket Money takes **35–60%** of savings; cancellation traps | Badly (trust gap *is* the feature) | Subscription detection + assisted-action bridge | **Build the cancel flow** | M–L |
| — | Couples / household | Unverified here; known category | Not at all (single-user by design) | None — green-field | Validate, likely defer | XL |

Effort: S ≈ days, M ≈ 1–2 wks, L ≈ 3–4 wks, XL ≈ quarter+.

---

## 2. Tier 1 — Already built; position and make legible (gaps 1–4)

These are the four deepest *trust* gaps in the market, and persFin is **architecturally incapable of violating them**. Minimal build; mostly product/marketing surfacing.

### Gap 1 — Human-in-the-loop AI (the master trust gap)
- **Demand:** AI-for-finance use leapt 10%→55% in a year, yet only **18%** would trust AI to make recommendations on its own; 55% prefer slower human-involved flows ([TD survey](https://stories.td.com/us/en/article/nearly-80-of-americans-use-ai-tools-but-most-still-want-humans-making-financial-decisions-td-survey-finds)).
- **persFin already is this.** The Clerk *proposes*; the user *confirms*; the next bank sync *verifies*. Money is never moved by the agent. See the assisted-action lifecycle in `server/src/services/assisted_action_service.py` and the propose/confirm token flow in `server/src/services/action_tokens.py`.
- **Move:** make it the headline ("the AI that does the homework and proves it — but never moves your money without you"). No build.

### Gap 2 — Verifiable AI (anti-hallucination)
- **Demand:** distrust of the *information* AI provides is a top reason people don't use finance chatbots (31% of non-users) ([FinHealth Network](https://finhealthnetwork.org/research/whats-holding-back-consumers-from-using-ai-financial-tools/)).
- **persFin asset:** the Chronicler's LLM never emits numbers — it renders a deterministic fact sheet (`server/src/services/game/chronicler.py`); the firewall screens output (`server/src/services/game/firewall.py`).
- **Implementation (small):** turn this architecture property into a *visible* feature — a "sources" affordance. The read tools already return the underlying rows; when the Clerk states a number, attach the transactions it came from.
  - In `server/src/services/assistant_service.py`, the streaming loop already inspects `on_tool_*` events and emits a `tool` SSE frame. Add a `sources` frame carrying the row ids/titles behind a stated figure (cap + PII-scrub via the existing `_safe_for_llm`). Client renders "based on these 7 transactions →".
  - Effort: S. Risk: low (read-only surface).

### Gap 3 — Incentive-aligned, no product-pushing
- **Demand:** users distrust free apps whose recommendations follow referral fees ([Monarch on Mint](https://www.monarch.com/blog/mint-shutting-down); corroborated by CFPB Circular 2024-01 and the FTC's Credit Karma action).
- **persFin asset:** the output firewall **blocks** recommending specific investments/products/loans (`_ADVICE_PATTERNS` in `firewall.py`) and the system prompt forbids it. persFin literally cannot do the thing users distrust.
- **Move:** state it plainly ("we never recommend a product for a kickback — we can't"). No build.

### Gap 4 — Privacy / no data-selling / local-first
- **Demand:** 60% of popular budgeting apps share user data with third parties, 1-in-4 share financial info; 71% of consumers would stop doing business with a company that gave sensitive data away ([Incogni 2026, via FinHealth corroboration](https://finhealthnetwork.org/research/whats-holding-back-consumers-from-using-ai-financial-tools/)).
- **persFin asset:** PII is scrubbed *before* reaching the LLM (`server/src/services/pii.py`, applied inbound and on every tool output); Plaid tokens are Fernet-encrypted at rest; raw receipt/tax images are dropped after extraction; SSN/EIN reduced to last-4; runs on local SQLite (`DATABASE_URL` configurable).
- **Implementation (small):** lean into **local-first / self-host** as a privacy SKU.
  - Document a self-host path (already feasible: SQLite + env-configured keys). Add a one-command compose/recipe and a "your data never leaves your machine" mode that disables outbound web tools (ties into the router's `WEB` group gating).
  - Effort: S–M (mostly packaging + docs + a "no-egress" settings profile).

---

## 3. Tier 2 — Mostly built; package into a segment wedge

### Gap 5 — Freelancer / irregular-income + taxes  ★ sharpest wedge

**Why it wins:** persFin already owns the two hardest pieces *no mainstream consumer app combines*: probabilistic cash-flow under variable income, and Schedule-C tax organization with quarterly estimate reminders.

**Demand (verified, with caveat):** freelancers need *cash-flow-based* budgeting — "budget money you HAVE, not money you expect" — plus a buffer that high months fund and low months draw from ([solofinancehub](https://solofinancehub.com/blog/best-budgeting-apps-irregular-income/)). Caveat: partially served by YNAB; **persFin's edge is the tax pairing, not irregular-income handling alone.**

**Existing assets:**
- `server/src/services/spend_service.py::safe_to_spend()` — dynamic, **paycheck-anchored** Safe-to-Spend; per-user config via `users.s2s_horizon|s2s_include_income|s2s_include_goals|s2s_buffer` (`db/models.py`).
- `server/src/services/forecast_sim.py` — block-bootstrap + conformal bands → overdraft probability (exactly the "will a thin month bite me" question).
- `server/src/services/recurring_service.py::next_paycheck_date()` — horizon anchor.
- Tax layer: `server/src/services/tax/` (Schedule-C buckets, summary) + `scheduler.py::job_tax_quarterly_reminder` (fires ~14 days before each estimated-tax due date with the user's YTD figures; gated by `tax_features_enabled`).
- Rules: `server/src/services/rule_engine.py` (`allocate` action → move %/$ of a transaction into a goal).

**Implementation plan:**
1. **Income-volatility → recommended buffer (new, small).** New `server/src/services/income_smoothing.py` (pure, like `forecast_sim`): compute monthly-income dispersion over a trailing window and recommend an `s2s_buffer` that covers a target percentile low month. Write the recommendation via the deterministic lane; the user accepts → set `users.s2s_buffer`. Reuses the bootstrap residual idea already in `forecast_sim`.
2. **Auto "tax set-aside" reserve (compose existing).** On freelance income, allocate a % to a dedicated **Tax** goal via a `rule_engine` `allocate` rule. Above the auto-execute threshold this surfaces a one-tap proposal (existing 2B path); below it earmarks silently. The quarterly reminder already closes the loop.
3. **Freelancer onboarding preset (new, small).** A setup flow that: sets `s2s_horizon` appropriately, enables `tax_features_enabled`, creates the Tax reserve goal, installs the allocate rule, and turns on subscription detection. One transactional bootstrap function calling existing services.
4. **(Optional) self-employment income classification.** Tag income sources as freelance vs W-2 so #1/#2 only smooth/reserve on variable income. Small addition to the income model + categorization.

**Effort:** M (the math/services exist; new code is the volatility→buffer calc + the onboarding preset). **Flag:** `freelancer_mode_enabled`, dark by default.

**Positioning:** "Know what's safe to spend *and* what to set aside for the IRS — built for 1099 income." Every Tier-1 trust property reinforces it.

### Gap 6 — ADHD / neurodivergent-friendly budgeting

**Why it fits:** persFin's game layer is, almost by accident, textbook executive-function-friendly design.

**Demand (verified):** mainstream apps "assume your brain works the same way every day, with consistent executive function" and fail neurodivergent users; 47% of adults with ADHD are dissatisfied with money management; served only by niche newcomers like Cake Budget ([Cake](https://www.trycakebudget.com/), [ADDitude](https://www.additudemag.com/)).

**Existing assets (the differentiator is already here):**
- `server/src/services/game/daily.py` — streaks that **rebuild rather than break** (no punishing "broken streak"); daily *tick* reward.
- `server/src/services/game/grace.py` — hardship **grace periods**: lapses incur no penalty, heat drops, XP still awarded.
- `server/src/services/game/heat.py` — a gentle stress signal that *falls* on saves/progress (not a guilt meter).
- `server/src/services/game/firewall.py` — **blocks shame** language in all output.
- `server/src/services/game/habit_monsters.py` + `challenges.py` — externalize habits into low-stakes, single, concrete actions.

**Implementation plan:**
1. **"One thing today" surface (new, small).** An endpoint returning the *single* highest-value next action (reuse the Keeper stats in `game/stats.py`, the active challenge, and any open assisted-action). Reduces decision fatigue / working-memory load — the core neurodivergent need.
2. **`neurodivergent_mode` profile (config tuning).** A settings flag that: widens `grace.py` generosity, lowers reminder frequency/noise, enlarges reward cadence, and defaults the UI to the single-action surface. No new mechanics — re-parameterize existing ones.
3. **(Frontend) visual "jars"/envelopes** over existing goals/earmarks (HyperJar-style), for users who need to *see* money partitioned. Mostly a client surface over `Goal.progress`.

**Effort:** M (backend is parameterization + one endpoint; the visible win is framing). **Flag:** `neurodivergent_mode`.

**Caution:** this is positioning of a real architectural strength — don't over-claim clinical benefit; frame as "doesn't assume a perfect-executive-function day."

---

## 4. Tier 3 — Genuine new build: honest subscription management

**The white-space:** Rocket Money proved the demand *and* poisoned the well. Its own Help Center confirms a **35–60% cut of first-year savings** for negotiation; BBB documents surprise charges for savings that never materialized or that users negotiated themselves, and cancellation/deletion **gated behind unpaid fees** ([RM Help](https://help.rocketmoney.com/en/articles/9744474-bill-negotiation-charge-explained), [BBB](https://www.bbb.org/us/md/silver-spring/profile/billing-services/rocket-money-inc-0241-236043013/complaints), [Reddit complaints](https://beelinger.com/rocket-money-complaints-reddit/)). The propose-verify bridge is the clean antidote: **detect → offer cancel → user acts → verify it stopped — for no cut of savings.**

**Existing assets:**
- Detection: `server/src/services/subscription_service.py::detect_subscriptions()` (merchant-normalized grouping, cadence classification, ≥2 occurrences) + `GET /subscriptions/` (`routers/subscriptions.py`).
- "Forgotten/zombie" signal: the F2 merchant-lifecycle enrichment (`probability_alive`, `lifecycle_status`, `price_change_pct`) behind `merchant_lifecycle_enabled` — i.e., *which subs you likely forgot* or that *quietly raised price*.
- Bridge: `AssistedAction` model (`db/models.py`) + lifecycle in `assisted_action_service.py`.
- Offer mechanism: the one-tap proposal pattern in `rule_engine.py::_propose_funding` (persist a `Notification` with a stable `ref`; mint the confirm token **on demand** via `action_tokens.make_token`).

**Implementation plan:**
1. **New assisted-action kind `subscription_cancel`.** Extend the `AssistedAction.kind` set; `how_json` carries the cancellation affordance (provider cancel URL / steps / deep link). It proposes a cancellation; it does **not** act. No money, no cut.
2. **Detect → offer job (new, reuses patterns).** A nightly pass (register in `scheduler.py` like `job_detangle`) over `detect_subscriptions()` output that flags candidates — low `probability_alive` (likely unused) or positive `price_change_pct` (silent hike) — and writes **one idempotent** `Notification` (`type="subscription_cancel"`, `ref=f"sub_cancel:{user}:{merchant}"`) offering a one-tap cancel bridge. Reuses `_propose_funding`'s persist-notification / mint-token-on-demand shape verbatim.
3. **Absence-based verification (new logic).** Today reconciliation verifies a charge *appearing* (`assisted_action_service.reconcile()` matches a transaction). A cancellation verifies a charge **disappearing**: mark the bridge `verified` when the expected `next_date` for that merchant passes with no matching charge in the next sync window. Add a small `verify_cancellation()` alongside the existing matcher, driven from the same Plaid-sync reconcile hook in `plaid_service.py`.
4. **Optional negotiation-assist (honest version).** The Clerk drafts a negotiation script/letter (it already has `search_web`/`open_website`) and proposes it as an assisted action — **flat or free, never a % of savings.** Pure information + propose-only; no execution, no contingency fee.

**Effort:** M–L (detection + offer pattern exist; new work is the `subscription_cancel` kind, the forgotten-sub detector wiring, and absence-based verification). **Flag:** `subscription_actions_enabled`.

**Positioning:** "Find what's draining you and cancel it in one tap — we never take a cut of your savings." Directly inverts the most-complained automation in the category.

---

## 5. Where persFin is genuinely behind (be honest)

### Couples / shared-household finances
- **Status:** **not supported, by design.** Every financial table is strictly single-user: `Account.user_id`, `Goal.user_id`, `Budget.user_id`, `Rule.user_id`, `AssistedAction.user_id`, etc.; every query filters by `current_user.id` (`auth_service.py` → service layer → `transaction_service._own_transaction`). There is no household, partner, shared-account, or permission concept. The **game layer is global/single-user** and `game/__init__.py` explicitly warns against partial multi-user changes (split-brain projection risk).
- **Blast radius:** XL / green-field. Multi-user would require a household/permission model, threading a `household_id` through ~30 tables *and* the game projections, reworking signup/auth for shared access, and per-user privacy controls on shared accounts.
- **Recommendation:** **validate demand before committing** (it did not surface in verified findings) and almost certainly **defer**. persFin's beachhead is *solo* freelancers and neurodivergent users — the opposite end from couples. Don't let an XL refactor crowd out the M-sized wedges that play to existing strengths.

### Unverified gaps (named in the brief, demand not confirmed here)
Treat as open questions, not opportunities, until validated: explicit "will-I-make-it-to-payday" forecasting demand (the generic claim was *refuted* as too vague — ironic given it's your strongest tech, so worth its own VoC test), multi-currency / immigrant needs, net-worth + investment unification, students, sinking-funds/envelope specifics.

---

## 6. Caveats on the demand data
- The headline AI figures (10%→55%, 18% trust) are from a single Feb 2026 **bank-sponsored** survey — directionally credible (cuts against sponsor interest) but one source.
- Rocket Money complaint data (BBB) is **self-selected and negatively skewed**; the app delivers genuine savings/cancellations for many. The gap is the trust-eroding *subset*, not total failure.
- The freelancer "unmet" framing is **partial** (YNAB serves much of the budgeting method); persFin's defensible edge is the **tax combination**.
- Do **not** quote these refuted claims: "variable income breaks standard apps," "mainstream apps fail freelancers outright," "Rocket Money keeps charging after cancellation," and several specific FNBO/Vixio adoption percentages — all failed verification.

---

## 7. Recommended sequencing

1. **Now (positioning, ~0 build):** message gaps 1 & 3 (human-in-loop, incentive-aligned) — pure validation of what exists.
2. **Sprint 1 (S):** gap 2 "cite sources" frame + gap 4 self-host/no-egress profile — small builds that make trust *visible*.
3. **Sprint 2 (M) — the wedge:** gap 5 freelancer mode (volatility→buffer + tax-reserve rule + onboarding preset). This is the sharpest market-advantage play.
4. **Sprint 3 (M):** gap 6 neurodivergent mode (one-thing-today + grace tuning).
5. **Sprint 4 (M–L):** gap 7 honest subscription cancel flow.
6. **Defer / validate:** couples/household and the unverified gaps.

Every item rides on the same trust spine (verifiable, no-autonomy, no-data-selling, no-product-pushing) that the market explicitly says it wants — which is persFin's real, already-built advantage.
