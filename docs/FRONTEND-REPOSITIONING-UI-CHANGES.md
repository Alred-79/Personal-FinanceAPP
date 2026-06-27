# Frontend / UI Repositioning — Lead With Strength, Reframe the Weak Fronts Honestly

**Status:** Design / Not started
**Companion to:** [MARKET-LANDSCAPE-ASSESSMENT.html](./MARKET-LANDSCAPE-ASSESSMENT.html) (the why) and [PHASE2-ASSISTED-ACTION-EXECUTE-DESIGN.md](./PHASE2-ASSISTED-ACTION-EXECUTE-DESIGN.md) (the money-movement reality this copy must not outrun)
**Last updated:** 2026-06-26

---

## 0. The thesis in one paragraph

The assessment found the app **advertises its three weakest, most-commoditized fronts**
("all your finances in one," "secure agent transactions / moves money," "forecasting") and
**stays silent about its three genuinely differentiated ones** (the freelancer/1099 tax wedge,
a correctly-built *read-only / propose-confirm* AI, and a gamification layer that rewards
*seeing & doing*, never spending). This document is the frontend work to flip that: **demote
the weak fronts, foreground the strong ones, and — where a weak or over-claimed feature stays
on screen — frame it honestly** (the single biggest example: the AI does **not** move money;
saying so plainly is both true and, per the trust data, a *selling point*).

Two principles drive every change below:
1. **Lead with the wedge.** A freelancer drowning in quarterly taxes is the user who would
   actually adopt this. The UI should speak to them first, not to a generic "track all your
   accounts" everyone.
2. **Honesty is a feature, not a disclaimer.** 75% of people are uncomfortable with AI that
   moves money autonomously; this app *doesn't*. Surfacing "nothing leaves your bank without
   your tap" turns our biggest perceived weakness into trust.

---

## 1. Copy law — words to kill, words to use

Apply globally (landing, onboarding, assistant, settings, app store text, meta tags).

| ❌ Stop saying | ✅ Say instead | Why |
|---|---|---|
| "Secure agent transactions" / "AI that moves your money" / "autonomous" | "Your AI drafts the move — **you** confirm it in your bank" | The code can't move money; the claim attacks a feature we don't have and triggers distrust. |
| "All your finances in one place" (as the hero) | "Built for freelancers: see your real number after taxes" | All-in-one is commoditized table-stakes; the freelancer angle is the wedge. |
| "Powerful forecasting" / "predict your future" (as a certainty) | "Know the odds you'll dip below zero before payday" | Forecasting is commoditized *and* probabilistic; sell the calibrated *risk*, not false certainty. |
| "Advanced analytics" (blanket) | name the specific thing ("spots a subscription that's quietly creeping up") | "Advanced" over-claims; concrete beats vague and survives the BG/NBD ≥5-merchant threshold. |
| "Automate your savings" (implying we pull money) | "We do the math; you approve the transfer" | Until Phase 2 ships behind a flag, we don't originate. Don't write a check the backend can't cash. |

**Tone:** plain, concrete, freelancer-literate. No hype adjectives ("powerful," "seamless,"
"revolutionary"). Numbers and verbs over abstractions.

---

## 2. Landing / `/welcome` — re-sequence the story

The landing currently foregrounds the commoditized capabilities. Re-order so the **first
screenful is the wedge** and the agent is framed honestly.

### 2.1 Hero (above the fold) — REPLACE
- **Headline:** the freelancer tax pain, not "all your money in one."
  e.g. *"Stop guessing what you owe in taxes."* / *"Your income is lumpy. Your safe-to-spend shouldn't lie about it."*
- **Subhead:** the honest mechanic — *"We set aside your tax %, smooth your lumpy income, and never move a dollar without your tap."*
- **Primary CTA:** "See my real number" (freelancer-flavored), not "Connect all accounts."
- **Trust chip under the CTA:** a small, persistent **"Read-only bank connection · nothing moves without you"** badge (see §6).

### 2.2 Section order — RE-RANK
Lead with strengths; move the commoditized stuff down and reframe it.
1. **Freelancer tax + irregular income** (the wedge): tax-reserve, quarterly estimate, income smoothing. *Hero of the page.*
2. **An AI that drafts, never sends:** show the propose → you-confirm → auto-reconcile loop as a *trust* feature (§4).
3. **Money as a game you can't cheat:** the gamify-*seeing* story (§5).
4. *(demoted, reframed)* See every account together — *table-stakes, stated plainly, not the headline.*
5. *(demoted, reframed)* Overdraft-odds forecasting — *as calibrated risk, with the honest "probabilistic" framing.*

### 2.3 Kill / rewrite any "agent moves money" hero moment
If the landing has a section dramatizing the agent *doing* things to your money, rewrite it to
dramatize the agent *preparing* the action and the human *confirming* it. The drama is "I did
the work, you keep the keys" — not "I moved your money."

---

## 3. Foreground the freelancer wedge (in-app)

The strongest, least-advertised asset. Make it a first-class surface, not buried in Tax.

- **Onboarding fork:** an early "Are you self-employed / 1099 / freelance?" branch. If yes,
  route into the freelancer setup (tax-reserve goal, income smoothing, quarterly estimate)
  as the **default home**, not an optional toggle.
- **Home/dashboard for freelancers:** lead the dashboard with **"Set aside for taxes"** and
  **"Your smoothed monthly paycheck"** cards above generic spend charts.
- **Quarterly estimate countdown:** a visible, dateline-driven card ("Q3 estimate due in 24
  days — projected $X") — this is the pain Catch's users describe; make it impossible to miss.
- **Honest threshold states:** the merchant-lifecycle / BG/NBD model needs ≥5 repeat merchants.
  Don't show a broken/empty chart — show an honest *"We'll spot subscription creep once you've
  got a few recurring charges"* empty state with progress toward the threshold.

---

## 4. The assistant / Bridge UI — make "drafts, you confirm" visible and proud

This is where the honest reframe lives in product, not just copy. The backend is already
propose → confirm → reconcile ([assisted_action_service.py](../server/src/services/assisted_action_service.py));
the UI should make that loop **legible and reassuring**, not hide it.

- **Bridge card language:** *"Here's the exact move. Tap to do it in your bank — I'll confirm
  it went through."* Never *"I'll handle it."*
- **Three-state Bridge chip** mirroring the real lifecycle: **Drafted → You do it → Verified ✓**
  (maps to `proposed/acknowledged` → user action → `verified` via reconcile). Showing the
  *verified-by-your-own-bank-data* step is a credibility win.
- **A persistent "what this assistant can and can't do" line:** *"I can see your transactions
  and draft actions. I can't move money or see full account numbers."* (Mirrors exactly the
  read-only line OpenAI drew — borrow the credibility.)
- **When Phase 2 ships (flag-on):** the *only* change is a "Send it" button that mints a
  single-use confirmation per action (see Phase 2 doc §7). Even then: per-action human tap,
  hard caps shown, and an explicit "you can turn this off" — never silent/autonomous.
- **No money-moving capability on the AI chat surface itself.** The chat proposes; a distinct,
  authenticated confirm UI executes. (Prompt-injection firewall, stated for the user.)

---

## 5. Gamification — show that it rewards *seeing*, never *spending*

The research's sharpest gamification finding: backfire apps reward spending ("the app
encourages you to SPEND to improve your city"); the winning pattern is *"gamify seeing, not
saving."* This app already does the right thing in code (XP only from verified money actions,
spending is never rewarded) — but the UI should **say so**, because it's a genuine differentiator.

- **An explainer on the game surfaces:** *"You earn XP for real money wins — paying a bill on
  time, funding a goal, closing a day under budget. Never for spending. You can't buy your way
  up."* This directly rebuts the "gamified finance is a gimmick" prior.
- **Anti-streak-shame:** keep surfacing the existing GRAY-day / Wards / Grace mechanics as
  *"a missed day won't break you"* — the research says streak-breakage is exactly why people
  quit gamified apps.
- **Tie XP to the wedge:** for freelancers, the highest-XP events should visibly be tax-reserve
  funding and quarterly-estimate payments — the game reinforcing the actually-valuable behavior.

---

## 6. Trust & honesty UI primitives (new, reusable)

Small components that turn our weakest-perceived points into stated strengths.

- **`<ReadOnlyBadge>`** — a persistent, quiet indicator wherever bank data appears:
  *"Read-only · we can see, not move."* One tap opens a plain-language explainer.
- **`<HumanInLoopBadge>`** — on every Bridge/action: *"Nothing happens until you tap."*
- **Honest empty/threshold states** (reusable pattern) — for any model that needs data density
  (BG/NBD ≥5 merchants, forecast needing history, income smoothing needing 3+ months): show
  *what's needed and progress toward it*, never a fake/empty chart.
- **Probabilistic framing component** for forecasts — always show the band + the odds
  ("~15% chance you dip below $0 before Fri"), never a single false-precise line.
- **A "What we don't do" section** (settings/about): *we don't sell your data, don't move money
  autonomously, don't recommend products for a kickback.* (The firewall already enforces the
  last one — surface it.) This is the Plaid-distrust and "you are the product" rebuttal.

---

## 7. De-emphasize, don't delete (the commoditized fronts)

Aggregation and basic forecasting stay — they're table-stakes users still expect — but they
**stop being the headline**:
- Move "all accounts in one view" to a supporting feature, described plainly.
- Frame forecasting as *calibrated overdraft odds* (the one genuinely-better-than-commodity
  bit), not "forecasting" in the abstract.
- Drop any superlatives ("most powerful," "advanced") that the assessment flagged as
  over-claims.

---

## 8. Surface-by-surface checklist

| Surface | Change | Priority |
|---|---|---|
| `/welcome` hero | Freelancer-tax headline + read-only trust chip; kill "agent moves money" | P0 |
| `/welcome` section order | Re-rank: wedge → honest-AI → game → (demoted) aggregation/forecast | P0 |
| Global copy | Apply §1 kill/use table everywhere incl. meta/app-store | P0 |
| Onboarding | Self-employed fork → freelancer setup as default home | P0 |
| Assistant / Bridge cards | "Drafts, you confirm" language + 3-state chip + can't/can line | P0 |
| Dashboard (freelancer) | Tax-reserve + smoothed-paycheck + quarterly-countdown as lead cards | P1 |
| Game surfaces | "XP for real money wins, never spending" explainer; anti-shame copy | P1 |
| Trust primitives | `<ReadOnlyBadge>`, `<HumanInLoopBadge>`, honest empty states, "What we don't do" | P1 |
| Forecast components | Probabilistic band + odds framing; drop false certainty | P2 |
| Aggregation/forecast sections | Demote + de-superlative | P2 |

---

## 9. Guardrails for implementation

- **Copy must not outrun the backend.** Until Phase 2 ships flag-on, no UI may imply the app
  moves money. The honest "you confirm in your bank" language is *required*, not optional.
- **Reuse, don't reinvent.** Build on the existing design system / landing primitives and the
  game surfaces already in the codebase; this is a *re-sequencing and reframing* pass, not a
  visual rebuild.
- **Accessibility & reduced-motion** parity for any new hero/landing changes (the landing
  already honors reduced-motion; keep it).
- **A/B worth running:** freelancer-tax hero vs. the current hero — the assessment predicts the
  wedge converts the user who'd actually pay.

---

## 10. What this explicitly does NOT change

- The visual identity / palette / motion language (re-sequence + reframe only).
- The game mechanics themselves (only their *explanation* changes).
- The backend (this is frontend copy/IA/components; money-movement is the separate Phase 2 doc).

---

### Traceability
Every change above maps to an assessment finding: §2–§3 ← "lead with the unowned freelancer
wedge"; §4, §6 ← "the agent doesn't move money — that's the safe, sellable truth"; §5 ←
"gamify seeing, not spending"; §1, §7 ← "stop advertising the commoditized weak fronts /
drop the over-claims." See [MARKET-LANDSCAPE-ASSESSMENT.html](./MARKET-LANDSCAPE-ASSESSMENT.html).
