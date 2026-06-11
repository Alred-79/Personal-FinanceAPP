# Behavioral moat — grounded evidence + concrete features

> The *why* behind [v3.md](./v3.md) (the *what/how*), rebuilt on two adversarial research passes
> (24 primary sources fetched, ~136 claims extracted, claims verified by 3-vote refutation +
> a second targeted verification batch). This doc is **deliberately unflattering**: several
> famous findings came back weaker than the popular framing, and those corrections are kept
> in-line rather than hidden. Every feature below is graded by the strength of its evidence.
>
> **Read the state check first** — almost none of the building blocks this references are built
> yet. The science's job is to *motivate and shape* the planned v1/v3 work and to set its
> sequencing, not to describe shipped features.

## State check (grounded against the codebase)

Both [v1.md](./v1.md) and [v3.md](./v3.md) open with **"Not yet executed."** As of this writing:

| Referenced building block | In code? |
| --- | --- |
| Agentic AI assistant (Groq + Tavily + hardened fetch + propose→confirm) | ✅ **Real** — `services/assistant_service.py`. The one true premise. |
| Income `recurrence` column | ⚠️ Defined in `db/models.py` but **not migrated**, **absent from `budget_ai.db`**. |
| Rules engine (`Rule` / `RuleExecution` / `rule_engine.py`) | ❌ Plan only (v1). |
| `birth_year` / percentile cohorts | ❌ Plan only (v1 enabler). |
| `project_cashflows` / `project_income` / fixed `will_go_negative` | ❌ Not built — `forecast_service.py` projects expenses only. |
| `safe_to_spend()` | ❌ Not built — still client-side `get_budget_allotment`. |
| `Liability` / debt boss | ❌ Plan only (v3). |
| Anti-dark-pattern "charter" | ❌ Prose in v3.md, not enforced. |

Read every "would" below as future tense.

---

## Evidence grading (what survived adversarial verification)

The two research passes split the canonical "behavioral moat" claims into three tiers. **The most
important correction: several headline figures are tiny single studies or failed preregistered
replications, and two of the deck's marquee claims were stated in their *refuted* form.**

### Tier 1 — load-bearing (robust, real-money or strong field evidence)

| Finding | What's actually supported | Caveat to keep |
| --- | --- | --- |
| **Goal-specific savings reminders** (Karlan, McConnell, Mullainathan & Zinman 2016, *Mgmt Sci*) | **The strongest result for this app.** 3-country real-money bank RCTs: reminders raised goal-attainment ~**3%** and amount saved ~**6%**; reminders that **name the user's specific goal ≈2× as effective** as generic. Externally replicated (Colombia youth SMS +28–43%). | Effects are *modest*; can be **null or annoying for financially-savvy users** — cap frequency, target. |
| **Save More Tomorrow** auto-escalation (Thaler & Benartzi 2004, *JPE*) | Saving rate **3.5%→13.6%** over 40 months; **78%** take-up among those who'd refused an immediate raise; **80%** retention through 4 raises. Mechanism = inertia/default. | 3.5→13.6 is the **first single-firm implementation**, not a population average. Effect rides on *employer-mediated automation*; self-directed app take-up is unproven. |
| **Commitment devices select present-biased users** (Ashraf, Karlan & Yin 2006 SEED, *QJE*) | **28%** take-up of a restricted-access product; concentrated among **time-inconsistent / sophisticated hyperbolic** users who know they have a self-control problem. | The famous **"42%/82% balance lift" was refuted (1-2)** — do **not** cite it. The *selection* result is the durable part. |
| **Scarcity impairs cognition — FIELD version only** (Mani et al. 2013, *Science*) | The **within-subject sugarcane-farmer** result (same people, poorer pre-harvest → measurably worse cognition) is robust and causal. | The **"~13 IQ points / night of lost sleep" lab-priming figure does NOT replicate** (O'Donnell 2021 PNAS: 4 of 20 studies; Carvalho 2016 AER payday null; authors' own self-replication failed Exp 1). **Live 2023 dispute** (Shah et al. vs O'Donnell). **Never cite the IQ-points number.** Use only the field/income-timing rationale. |

### Tier 1-but-caveated — real, but smaller or narrower than the headline

| Finding | Reality after verification |
| --- | --- |
| **Future-self / aged avatar** (Hershfield 2011, *JMR*) | Confirmed (d≈.52 / .74) but **small N, one-tailed in Study 1, hypothetical allocation DV.** The broader "future-self contact shifts intertemporal choice" mechanism was **refuted (0-3).** Treat as *directional* support for making the future vivid, not a guaranteed lever. |
| **Mental accounting / partitioned earmarks** (Soman & Cheema 2011, *JMR*) | One credible real-money field RCT: physically partitioning earmarked savings ≈**+72%** (N≈146, **unreplicated**). But **earmarking that locks liquidity backfires** when the goal isn't urgent (Dupas & Robinson 2013: locked health-savings *reduced* saving). Ship soft, reversible, default-on labels — **never hard locks, never "guilt-free" framing** (that reverses the effect). |
| **Fresh-start effect** (Dai, Milkman & Riis 2014, *Mgmt Sci*) | Best causal evidence is the **2021 savings field RCT (~+25% contributions)**, not the viral gym percentages (those are archival/correlational). **Only landmarks that signal a new beginning work** (control holidays did nothing). **Backfires for users already on a streak** (Dai 2018 "double-edged sword" — resetting demotivates winners) and risks the **"what-the-hell effect."** A 61k-person 2021 megastudy found fresh-start framing did *not* reliably boost behavior. Use as a gentle *re-entry* affordance, never as a streak reset for people doing well. |
| **Implementation intentions / if-then plans** (Gollwitzer & Sheeran 2006) | d≈0.65 is **accurately cited but an inflated ceiling.** Authors' 2024 update: .27–.66 with confirmed publication bias; an RCT of 877 gym members was a **tight null**; a Dutch bank savings-nudge raised *clicks* but **not actual savings.** **No meta-analytic evidence for if-then plans on spending/saving.** Realistic effect ~d 0.15–0.35; works for **one-off actions**, weak for **ongoing habits.** |
| **Pain of paying / cashless** (Prelec & Simester 2001) | The "credit cards ≈ 2× willingness-to-pay" figure is **one tiny auction (N≈64)** that **failed a preregistered replication** (Liu & Dewitte 2021). The defensible number is the 2024 meta-analysis: a **small (~d 0.1–0.2), shrinking, context-dependent** effect that **mobile wallets don't reliably inherit.** Use only as soft rationale for re-introducing *felt consequence*; never quote a doubling. |
| **Prize-linked savings** | Robust: **attracts non-savers and substitutes for gambling.** Causal savings lift is **~1% of annual income** (quasi-experimental field), **not** the 25% lab/hypothetical number; the one true RCT (Kenya) was **null/underpowered.** Backfire: least helps the most gambling-vulnerable. **Deferred in v3 — keep it deferred.** |

### Tier 2 — marketing/survey color (NOT evidence; do not build a moat on these)

- **"Ostrich Effect = avoid checking when finances hurt"** — **this popular framing is REFUTED (1-2).**
  The verified finding (Karlsson, Loewenstein & Seppi 2009, 3 Scandinavian datasets) is narrower:
  **asymmetric monitoring** — people check **more in up-markets, less in down-markets.** The avoidance
  *loop* is still a reasonable design premise, but cite it as asymmetric monitoring, not "ostriching."
- **"Money dysmorphia," "doom spending," "83% / 216M financially stressed"** — Credit Karma / Edward
  Jones-Gallup **pop surveys.** Fine as narrative color in marketing; **never load-bearing.**
- **"LLM coaching improves financial outcomes"** — **no causal evidence exists.** The best 2026 study
  (Choukhmane/de Silva NBER) is a *simulated advice-quality audit*, not a behavior RCT, and it found
  the model gives **systematically biased advice** (recommends lower equity to women on identical
  prompts; worse advice to low-literacy/low-AI-experience users — widening gaps 4–6% of retirement
  wealth) plus hallucinated numbers and sycophancy. **The agent is a real moat as plumbing, but it
  cannot claim an evidence-backed coaching mechanism.** This directly constrains R3 (see below).

---

## The thesis (corrected)

The durable bet is **not** "the first app engineered to be approached" (Finch already proved
zero-guilt is copyable, and "ostriching" is the wrong mechanism anyway). It is the combination
**no incumbent has**: **live bank data + a real cashflow forecast + an agent that can act
(propose→confirm)**, used to deliver the *few* behavioral interventions that actually survive
scrutiny — **goal-named reminders, default-on auto-escalation, soft earmark partitioning,
commitment for the self-aware present-biased, and just-in-time cashflow nudges** — and to **avoid
the documented backfires** (over-reminding, hard locks, streak resets, guilt framing, biased AI
advice). The moat is *integration depth + restraint*, not gamified gentleness.

## North-star metric (kept — it's the best idea in the original deck)

Optimize **"did the user act on a hard day?"** and *did financial anxiety / avoidance fall?* — not
DAU. This is what makes the anti-dark-pattern stance *also* the strategy, and it's incompatible with
an engagement-maxxing model. It is also the **honest** metric given the evidence: most effects above
are small, so the win is *did the intervention move real money/behavior*, measured against a holdout.

---

## Concrete features (graded; each maps to the existing/planned stack)

Format: **mechanism → exact design → metric → backfire mode.** Ordered by evidence strength.

### F1 — Goal-named smart reminders *(Tier 1, build first)*
- **Mechanism:** limited-attention salience; naming the specific goal ≈2× generic (Karlan 2016).
- **Design:** the agent (`assistant_service.py`) emits a reminder via `notification_service` that
  **names the user's actual goal and current progress** ("You're $40 from *Japan trip* — move
  today's $12 round-up?") with a one-tap propose→confirm `allocate` to that `Goal`. Cadence-capped
  (≤1–2/week), tied to real cashflow events (post-payday, under-budget week), **not** app-opens.
- **Metric:** RCT vs a no-reminder holdout — goal-attainment rate and Σ`Goal.progress` deposits.
  Expect *small* (~3–6%); ship only if it beats holdout.
- **Backfire:** null/annoying for savvy users → suppress for users already hitting goals; hard
  frequency cap; user-controllable. (Maps to v1 rules engine + existing notifications + agent.)

### F2 — "Level up savings" auto-escalation *(Tier 1)*
- **Mechanism:** inertia/default; pre-commit future increases (Save More Tomorrow).
- **Design:** a `Rule` (v1 engine) that **escalates a recurring `allocate` on a schedule or on
  detected income rises** (raise visible via Plaid income stream) — "+1% of pay to savings each
  payday until you say stop." Opt-in, framed as character leveling in v3 but the substance is
  auto-escalation. Default-on increments, trivially pausable.
- **Metric:** savings-rate slope over months for enrolled vs not; retention through ≥3 escalations.
- **Backfire:** escalating into a deficit → **gate every increase behind the forecast**
  (`project_cashflows`): never escalate if it pushes `will_go_negative`. Always reversible.

### F3 — Just-in-time payday/forecast nudge *(Tier 1 — the field-evidenced scarcity version)*
- **Mechanism:** the *defensible* scarcity finding — timing-of-money matters; act when cash is
  present, not when depleted. (Field/income-shock evidence only; **no IQ-points claim.**)
- **Design:** when `project_cashflows` shows incoming pay, the app surfaces a **single
  pre-commitment beat** at payday ("$X landed — lock $Y to goals before it's spent?"). When it
  detects strain (low balance / pre-payday trough), the UI **collapses to one number + one action**
  (the Safe-to-Spend `available` + the single highest-value move) instead of more dashboards.
- **Metric:** % of paydays with a pre-spend allocation; whether strain-mode users complete the one
  action vs. the full dashboard (A/B).
- **Backfire:** turning a hard day into a guilt prompt → strain-mode copy is supportive and
  *reduces* demands, never adds them; **frame around income timing, never "scarcity makes you dumber."**

### F4 — Soft goal-partitioned earmarks *(Tier 1-caveated)*
- **Mechanism:** partitioning earmarked money raises saving (Soman & Cheema), but **locking it
  backfires** (Dupas & Robinson).
- **Design:** `Goal.progress` already is a virtual earmark that reduces Safe-to-Spend. Make each
  goal a **named, visible sub-bucket** with the goal's label and a progress cue. **Default-on,
  instantly reversible, never a hard lock; never "guilt-free" framing.**
- **Metric:** saving rate with partitioned vs single-bucket earmarks; raid frequency.
- **Backfire:** over-restriction / liquidity cost → always allow pull-back; warn if earmarking
  starves a near-term bill the forecast sees coming.

### F5 — Commitment mode for the self-aware *(Tier 1-caveated, opt-in only)*
- **Mechanism:** sophisticated present-biased users *want* a commitment device (SEED selection).
- **Design:** an **opt-in** "lock until date/goal" on a goal — a *soft* commitment (extra friction +
  a confirm to withdraw early, not a real legal lock, since transfers are virtual). Surface it only
  to users who signal a self-control goal (don't push it on everyone).
- **Metric:** opt-in rate; goal-completion for committers vs non; early-break rate.
- **Backfire:** locking liquidity someone needs → the forecast must veto a lock that would cause a
  shortfall; early-exit always available with a gentle confirm, never a penalty.

### F6 — Landmark re-entry (NOT a streak reset) *(Tier 1-caveated)*
- **Mechanism:** fresh-start framing aids *re-initiation* — but **only real "new beginning"
  landmarks**, and it **demotivates people already winning.**
- **Design:** at month/year/birthday boundaries, offer a **gentle re-entry** to lapsed users
  ("new month — want to restart the round-up habit?"). For v3's roguelike "monthly runs," the clean
  slate is the *anti-abandonment* affordance — but **do not reset streaks/progress for users who are
  on track** (Dai 2018). Make the reset opt-in and skip it for the engaged.
- **Metric:** reactivation rate of *lapsed* users at landmarks vs non-landmark days; check engaged
  users are *not* harmed (no drop after resets).
- **Backfire:** "what-the-hell" licensing + demotivating winners → target lapsed users only.

### R3 constraint — AI narrator as *flavor + plumbing*, never advice authority *(Tier 2 evidence)*
- The agent is a real moat **as plumbing** (it can read data, search the web, and route
  propose→confirm writes — incumbents can't). It is **not** an evidence-backed *coach*: LLM
  financial advice is unproven on behavior and **documented to be biased, hallucination-prone, and
  sycophantic.** So R3 must stay inside the **two-layer law already in v3.md**: deterministic engine
  is authority; the LLM does narration/quests/spell-drafting and **every number it shows is
  recomputed by the engine, every action it proposes goes through confirm.** Add a **bias guard**:
  never let generated copy give allocation/equity-style *advice*; ground all judgments in the user's
  real data, not the model's priors. This is both an ethics line and a correctness line.

---

## What to cut or demote (the adversarial part)

- **Drop the "Ostrich Effect" framing** as written — it's the refuted version. Keep the avoidance
  *loop* as a soft premise, cited as asymmetric monitoring.
- **Never quote** the "~13 IQ points," the SEED "42%/82%," the cashless "≈2×," or the PLS "25%"
  figures. Each is a single study, a refuted claim, or a hypothetical-DV lab number.
- **Keep prize-linked savings deferred** — weak causal evidence, real backfire on the vulnerable.
- **Don't claim the AI coaches.** It automates and narrates; it does not improve outcomes by evidence.
- **Treat all pop-survey % as marketing color**, never as the rationale for a feature.

## Sources (primary, by claim)

**Tier 1 / load-bearing:**
- Karlan, McConnell, Mullainathan & Zinman (2016), "Getting to the Top of Mind: How Reminders
  Increase Saving," *Management Science* — https://pubsonline.informs.org/doi/10.1287/mnsc.2015.2296
- Thaler & Benartzi (2004), Save More Tomorrow, *JPE* — https://www.journals.uchicago.edu/doi/10.1086/380085
- Ashraf, Karlan & Yin (2006), SEED commitment savings, *QJE* — https://academic.oup.com/qje/article-abstract/121/2/635/1884028
- Mani, Mullainathan, Shafir & Zhao (2013), *Science* (use the **field** result) — https://www.science.org/doi/10.1126/science.1238041
- O'Donnell et al. (2021), scarcity-priming non-replication, *PNAS* — https://www.pnas.org/doi/10.1073/pnas.2103313118 ; Carvalho, Meier & Wang (2016), *AER* — https://www.aeaweb.org/articles?id=10.1257%2Faer.20140481 ; Shah et al. (2023) rebuttal — https://www.pnas.org/doi/10.1073/pnas.2206054120

**Tier 1-caveated:**
- Hershfield et al. (2011), future self, *JMR* — https://journals.sagepub.com/doi/10.1509/jmkr.48.SPL.S23
- Soman & Cheema (2011), partitioning, *JMR* — https://journals.sagepub.com/doi/10.1509/jmkr.48.SPL.S14 ; Dupas & Robinson (2013), *AER* (lock backfire) — https://www.aeaweb.org/articles?id=10.1257/aer.103.4.1138
- Dai, Milkman & Riis (2014), fresh start, *Mgmt Sci* — https://faculty.wharton.upenn.edu/wp-content/uploads/2014/06/Dai_Fresh_Start_2014_Mgmt_Sci.pdf ; megastudy null — https://www.nature.com/articles/s41586-021-04128-4
- Gollwitzer & Sheeran (2006) + 2024 update — https://www.tandfonline.com/doi/abs/10.1080/10463283.2024.2334563 ; gym null — https://www.nber.org/papers/w24959
- Prelec & Simester (2001) — https://link.springer.com/article/10.1023/A:1008196717017 ; 2024 meta-analysis — https://www.sciencedirect.com/science/article/pii/S0022435924000216 ; Liu & Dewitte (2021) replication failure — https://www.sciencedirect.com/science/article/abs/pii/S0969698921000382
- Prize-linked savings: Cole, Iverson & Tufano (2022), *Mgmt Sci* — https://ideas.repec.org/a/inm/ormnsc/v68y2022i5p3282-3308.html ; Cookson (2018), *JFE* — https://ideas.repec.org/a/eee/jfinec/v129y2018i1p24-45.html

**Tier 2 / color & cautions:**
- Choukhmane, de Silva et al. (2026), AI financial advice audit — https://www.timdesilva.me/files/papers/llm_advice.pdf ; LLM financial hallucination — https://arxiv.org/abs/2311.15548
- "The budgeting-app trap: when spending information backfires" — https://www.behavioraleconomics.com/the-budgeting-app-trap-when-spending-information-backfires/
- Pop-survey color (doom spending / money dysmorphia / 83% stress) — Credit Karma & Edward Jones-Gallup commentary (treat as marketing).

> Cross-references: competitor/uniqueness audit, retention data, and Robinhood/FINRA precedent live
> in [v3.md](./v3.md). This doc does not duplicate them.
