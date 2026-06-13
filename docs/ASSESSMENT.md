# Personal-FinanceAPP — Full Assessment

*Independent audit of correctness, the agent read/write model, the data layer,
best-practice conformance, competitor positioning, and product readiness.*

**Date:** 2026-06-13 · **Method:** code review + both test suites run + a live
adversarial red-team pass (probes A–G) against the app via an isolated harness
(throwaway in-memory DB, fresh JWT secret, two seeded users, no outbound API calls).
No source files were modified. Every claim below is backed by a probe id or a
`file:line`.

---

## 1. Executive verdict

**Is this a real, working product?** Yes — substantively. It is a ~35k-line
full-stack app (≈19.6k server / ≈15k client) with **802/803 backend tests and
167/167 frontend tests passing**. The core finance loop (accounts → transactions →
budgets → goals → forecast → safe-to-spend → net worth) is genuinely wired with real
server-side math, not mock data. The standout engineering — the MCP agent surface and
the assistant's write-safety — is real and, on several axes, **ahead of industry
norms**.

**Does it do what the UI claims?** ~95%. The finance features and the large
gamification layer are wired end-to-end. Three honest disconnects exist (§4), and a
few README sentences over-claim relative to the code (§2.3, §5).

**Is there a frontend/backend disconnect?** Minor and specific, not systemic:
- **MCP key management has no UI** — the `/api/mcp-keys/` CRUD is fully implemented
  server-side but unreachable from the app (you can't create the key the README's
  whole agent story depends on without `curl`).
- **The Homestead "commit" button is inert** — it renders, the server prepares the
  action payload, but the client wires no `onClick`.
- **No rule-creation UI** — the rules engine exists and badges show automation, but
  rules can only be read from the UI, not created.

**The one thing to fix before trusting it with real money + a real LLM:** the in-app
assistant sends **raw financial data to a third-party LLM with no redaction** and
its chat output is **not screened by the advice/crisis firewall** that the codebase
already contains (it's wired only to the game surface). See §2.2 / P0 in §7.

**Single sentence:** A genuinely impressive, security-conscious personal build whose
*agent write-safety and MCP boundary are production-grade*, held back from being a
shippable product by data-privacy gaps in the chat assistant, a single-worker
concurrency ceiling, and the absence of multi-tenancy + Plaid-production compliance.

---

## 2. Security & correctness (the agent read/write model)

### 2.1 What is genuinely strong (verified live)

| Guarantee | Verdict | Evidence |
| --- | --- | --- |
| **Auth — forgery rejected** | ✅ | alg=none, wrong-secret, expired all → 401 (probe **A1/A2/A3**). Decoder pins `algorithms=[HS256]` (`auth_service.py:367`). |
| **Refresh rotation + family revocation** | ✅ | Reusing a rotated refresh token → 401 *and* revokes the whole lineage (probe **A5/A5b**; `auth_service.py:221-226`, RFC 6819 §5.2.2.3). |
| **Cross-user isolation (IDOR)** | ✅ | alice reading bob's account → 404 (probe **A6**; matches `test_v2_features`). |
| **Assistant cannot write directly** | ✅ | LLM only *proposes*; the only write tools return `needs_confirmation` (`assistant_service.py` `_propose_action`). Probe **B1**: propose writes 0 rows. |
| **Confirm is single-use (replay-proof)** | ✅ | Confirm once writes 1 row; replay → **409**, still 1 row (probe **B2/B3**). Enforced by a DB `UNIQUE(jti)` on `used_action_tokens`, claimed in the same txn as the write (`assistant.py:175`). |
| **Token-type isolation** | ✅ | Access token used as a confirm token → 400; wrong-`typ` forged action token → 400; cross-user confirm → 403 (probe **B4/B5/B6**). |
| **MCP — only one DB door** | ✅ | `vault.py` is the sole importer of `SessionLocal`; the AST import-guard detector bites on a planted violation (probe **C8**; `test_mcp_import_guard.py`). |
| **MCP — capabilities only narrow** | ✅ | Requesting a scope not on the key → `PolicyError`; subset mints fine; empty scope rejected (probe **C2/C3/C5**; `policy.py:71-78`). |
| **MCP — capability type confusion** | ✅ | An auth token cannot be verified as a capability (probe **C4**; `policy.py:113`). |
| **MCP — audit redaction** | ✅ | A read with secret params logs `params_hash` only; raw `super_secret_value`/SSN never appear (probe **C6**; `audit.py:30-79`). |
| **MCP — unauth surface** | ✅ | `/mcp` without a key → 4xx; ships dark (`mcp_enabled=false`) by default (probe **C1b**; `settings.py:120`, `main.py:50`). |
| **SSRF-hardened web fetch** | ✅ (code-verified) | All DNS records validated, private/link-local/metadata ranges blocked, redirects re-checked per hop, socket pinned to the validated IP, TLS still verifies the host (`assistant_service.py` `_resolve_validated`/`_fetch_and_strip`; `test_assistant_security.py`). |
| **Money is integer cents end-to-end** | ✅ | Banker's rounding holds (`2.675→268`, `10.99→1099`), round-trips are stable, NaN/Inf/over-cap rejected at the API (probe **E1/E2/E3**; `money.py`, `models.py:16`). |

This is a real, defensible security model. The propose→confirm→one-time-token design
and the read-only audited MCP vault are the kind of controls most products in this
space **do not** implement.

### 2.2 Confirmed gaps (security — both lenses)

- **[P0] No PII redaction before the in-app assistant calls Groq.** The assistant
  ships raw merchant titles, account names, and amounts to `llama-3.3-70b-versatile`.
  There is no redaction primitive anywhere in `assistant_service.py` (probe **B8**;
  `grep -i redact|mask|scrub` is empty). The README's "redacts" claim covers only the
  MCP audit log, **not** this path. For an app handling financial data this is the
  single most material privacy gap.

- **[P0] The advice/crisis/shame firewall guards the wrong surface.**
  `server/src/services/game/firewall.py` (investment-advice blocking, shame-language
  suppression, 988 crisis routing) is imported **only** by `routers/game.py` and the
  game services (probe **B7**: firewall importers are all under `game/`). The headline
  `/api/assistant/chat/` streams raw Groq tokens with **no** advice/crisis screening,
  and the `redteam_prompts.txt` corpus is exercised only against the Chronicler. A user
  chatting the main assistant can elicit unlicensed investment advice or unscreened
  crisis content.

- **[P0] No prompt-injection defense on the main assistant.** It reads
  attacker-influenceable text (Plaid merchant names, fetched web pages) with no
  instruction/data separation, no output validation, and **zero injection tests**. This
  is OWASP LLM01 (2025), the #1 ranked LLM risk. *Mitigating context:* the
  propose→confirm gate means injection cannot force a **write** — the blast radius is
  "influence what the assistant says," not "move money."

- **[P1] The LLM cost cap is advisory on the streaming path.** The hard cap is
  *requests/day* (100), which does hold. The *token* budget is explicitly
  "ADVISORY / observability only" because `astream_events` surfaces no usage metadata
  (`settings.py:92-95`) — so a few very long requests can run up cost under the request
  cap. The code is honest about this; the README's "denial-of-wallet" framing is not.

- **[P1] The MCP vault is single-worker-only (not a data leak).** The failing test
  `test_concurrent_cross_user_vault_reads_never_mix` errors on a `sqlite3.InterfaceError`
  (shared-connection misuse under an in-memory `StaticPool`), **not** on a cross-user
  row mix — the leakage assertion is never reached (probe **C7**;
  `test_mcp_failure_modes.py:452`). The real limitation: `vault.read` opens sessions
  from a module-level engine and is only safe under the **single-worker invariant** the
  settings already document for the scheduler and rate-limiters (`settings.py:54-59`).
  The invariant is load-bearing and undocumented *at the vault layer*. The test's
  StaticPool setup overstates the production (file-DB) risk, so the failing test should
  be reframed, not just chased.

- **[P2 / note] Access path ignores `typ`.** `get_current_user` authenticates any
  token signed with the real secret that carries a `sub` claim, regardless of `typ`
  (probe **A4**). Not currently exploitable (capability/action tokens use `uid`, not
  `sub`), but defense-in-depth would assert the access path rejects a non-empty `typ`.

### 2.3 README claims vs. reality

| README says | Reality |
| --- | --- |
| "reads your finances … **redacts** …" | True for the **MCP audit log**. **False** for the in-app assistant, which ships raw data to Groq. |
| "denial-of-wallet … LLM10" cap | The **request** cap enforces; the **token** cap is advisory-only on streaming (settings says so explicitly). |
| "The session is never committed" | True for the **vault** session; the MCP auth middleware *does* commit a `last_used_at` metadata write on first use. |

---

## 3. Data layer (DB, ingestion, quality, retrieval)

**Schema & retrieval.** Clean, multi-tenant-ready schema; every financial table is
`user_id`-scoped with cascade deletes. There is **one shared read layer**
(`services/read_queries.py`) used by REST, the MCP vault, and the assistant — verified,
no bypass. Money columns are all `Integer` cents; the single cents→dollars conversion
happens once at the read seam, and the client never double-converts (the few `/100`
sites are where the server intentionally sends raw cents, e.g. Homestead).

**Input validation is genuinely good** (better than first appearances): money fields
use `allow_inf_nan=False, ±1e12` (NaN/Inf rejected, negatives allowed for refunds by
design), titles are capped at 200 chars, dates are typed (`models.py:16,28`). Probe
**D6**: malformed date → 422; probe **E3**: over-cap/NaN rejected.

**Ingestion.** Plaid sync is cursor-based and idempotent (partial `UNIQUE` index on
`plaid_transaction_id`; a SAVEPOINT-guarded deduped insert). Non-USD and `$0`
transactions are deliberately skipped; titles are truncated to 200.

**Confirmed data findings:**
- **[P1] Plaid re-sync silently overwrites manual edits.** `_process_modified` sets
  `expense.title/.amount/.date/.category` from the payload with no protection for
  user-edited fields and no UI warning (`plaid_service.py:705-709`). A user who
  corrects a transaction will see it reverted on the next sync. Intentional (Plaid as
  source of truth) but **undocumented and user-visible**.
- **[P2] "Learns money per merchant" oversells it.** Categorization is a deterministic
  merchant lookup + hardcoded keyword rules + a cached LLM fallback row — not ML/stats
  (`categorization_service.py`).
- **[P2] USD-only; server-local day boundaries.** Non-USD is dropped silently; dates are
  bare `date` with no timezone handling — fine for one US user, a correctness risk for a
  multi-timezone/multi-currency product.
- **[note] Manual entry is intentionally permissive** ($0 and future-dated manual
  expenses are accepted; probes **D1/D4**) — reasonable for scheduled/known entries, but
  worth a deliberate product decision.

---

## 4. Frontend ↔ backend wiring

Core finance pages are **WORKING** end-to-end with real backend math: Overview,
Transactions, Accounts, Budgets (`on_pace` prorated server-side), Goals, Subscriptions,
**Forecast** (`ForecastService` projects the balance timeline), **Safe-to-Spend**
(`SpendService`), **Net Worth** (snapshot series), Cashflow Calendar (forecast nodes).
The 401→refresh queue works as the README describes — auth endpoints bypass the queue
to avoid the self-await deadlock (`lib/api.ts:50`). Settings persist and take effect
(S2S prefs re-fetch immediately; game mode flips the DOM skin).

The large game layer (Debts/Keeper/Campaigns/Expedition/Outcomes/Homestead) is **wired
and gated** by the intensity flag; "off" mode is genuinely pure-finance, and setting the
mode emits no game events (`test_game_mode_api`). Its append-only event log is enforced
by **DB triggers** (`RAISE(ABORT)` on UPDATE/DELETE of `game_events`) and never mutates
the financial ledger (35 game-integrity tests pass; fingerprint checks on every game
test).

**Disconnects:** MCP-key UI missing · Homestead commit button inert · no rule-creation
UI (all in §1).

---

## 5. Best-practice conformance (cited)

Measured against **OWASP LLM Top 10 (2025)**, the **MCP spec security best-practices**,
and current financial-LLM guidance:

**Ahead of the norm.** Read-only MCP tools, capability tokens that *only narrow*, scope
minimization, per-read hashed audit, `mcp_enabled=false`-by-default, SSRF DNS-pinning,
and propose-then-confirm writes are all *explicitly recommended* controls that most MCP
servers don't implement (>half of open-source MCP servers rely on static broad
secrets). The MCP spec's "Scope Minimization" and "Token Passthrough" anti-patterns are
both avoided here; capability tokens are minted *to* the server, not passed through.

**Behind the norm.** No LLM input/output guardrails on the main chat, no PII
minimization before third-party inference (current guidance: rule-based redaction at the
egress, *not* an LLM doing the redaction), no injection test coverage, advisory-only cost
cap, and no advice/crisis firewall on the headline assistant.

Sources:
- [OWASP Top 10 for LLM Applications 2025 (PDF)](https://owasp.org/www-project-top-10-for-large-language-model-applications/assets/PDF/OWASP-Top-10-for-LLMs-v2025.pdf)
- [MCP Security Best Practices](https://modelcontextprotocol.io/specification/draft/basic/security_best_practices)
- [LLM Guardrails for Fintech (hallucination, audit, PII)](https://www.getmaxim.ai/articles/llm-guardrails-for-fintech-compliance-hallucination-prevention-and-audit-trails/)
- [Why using an LLM to redact PII is a bad idea (use rule-based)](https://blog.philterd.ai/why-using-an-llm-to-identify-and-redact-pii-and-phi-is-a-bad-idea/)

---

## 6. Competitor positioning & business scope

**Market (2025-2026).** Monarch (~$100/yr), Copilot (~$95/yr, iOS-first), YNAB
(~$109/yr), Simplifi — all now ship AI features, but those assistants are
**overwhelmingly read-only** insight/chat/categorization. A **scoped, audited,
write-safe agent surface over MCP** is genuinely differentiated — but it is an
*enthusiast/developer* differentiator, not a mass-market one. Most users will never
connect an external agent; the differentiator's audience is small.

Sources:
- [Best AI personal-finance tools 2026 (YNAB/Copilot/Monarch/Simplifi)](https://www.techno-pulse.com/2026/04/best-ai-personal-finance-tools-in-2026.html)
- [Copilot vs Monarch 2026](https://x1wealth.com/compare/copilot-vs-monarch)

**Realistic scope today: a portfolio-grade / self-host single-user app.** It is
effectively **single-user in practice** (`single_user=True` closes registration after
the first account; `settings.py:36`) even though the schema is multi-tenant-ready. To
become a real product:
1. **Remove the single-worker invariant** (vault, scheduler, in-memory rate-limiters all
   assume one worker) before any multi-tenant deployment.
2. **Plaid production access** + the compliance that triggers: the **GLBA / FTC
   Safeguards Rule** requires a written information-security program, named accountable
   owner, access controls, and breach notice (≥500 consumers within 30 days). Plaid also
   *contractually* requires a GLBA-aligned security program and data-deletion on request.
3. **Multi-tenancy, onboarding, support, and a third-party data-processing posture** for
   shipping financial PII to Groq/Tavily.

Sources:
- [FTC Safeguards Rule 2026](https://northstartechnologygroup.com/resources/ftc-safeguards-rule-2026-financial-services-compliance)
- [Plaid §1033 / third-party data obligations](https://plaid.com/resources/compliance/section-1033-authorized-third-parties/)

---

## 7. Prioritized remediation backlog

**P0 — before trusting it with real money + a real LLM**
1. **Redact PII before the assistant's Groq calls** — rule-based scrubbing of merchant
   names / account names / amounts at the egress (not an LLM doing the redaction).
   *Finding B8 / §2.2.*
2. **Route `/api/assistant/chat/` output through `firewall.py`** (advice/crisis/shame),
   the screening already built for the Chronicler. *Finding B7 / §2.2.*
3. **Prompt-injection defense + an injection test suite** seeded from
   `server/tests/fixtures/redteam_prompts.txt`, applied to the main chat, not just the
   game surface. *§2.2.*

**P1 — before multi-user / production**
4. **Enforce the token/cost budget on the streaming path** (or stop presenting it as a
   cap). *§2.2.*
5. **Make the vault concurrency-safe or hard-enforce single-worker** — reframe the
   misleading failing test (it tests StaticPool misuse, not row-mix) and document the
   invariant at the vault layer. *Finding C7 / §2.2.*
6. **Protect or surface the Plaid-overwrites-manual-edits behavior** (preserve
   user-edited fields, or warn in the UI). *§3.*

**P2 — honesty & polish**
7. Correct README over-claims ("redacts", token "denial-of-wallet" cap, "never
   committed"). *§2.3.*
8. Ship the **MCP-key management UI** (the agent story is unreachable without it).
9. Wire the **Homestead commit action**; add a **rule-creation UI**.
10. Assert `typ` on the access path (defense-in-depth). *Finding A4.*

---

## 8. How to reproduce

- Backend baseline: `.venv/bin/python -m pytest server/tests` → **802 pass / 1 fail**
  (the concurrency test, classified in §2.2). Frontend: `npm run test -- --run` → **167
  pass**.
- The red-team probes ran via an isolated harness (real ASGI app, in-memory DB, fresh
  JWT secret, two users, `mcp_enabled=true` dev-only, **no outbound calls**). No project
  source was modified (`git status` clean throughout). Live-key legs (Plaid sandbox sync,
  Groq chat injection) were verified from code rather than executed, to avoid burning
  real credentials.
