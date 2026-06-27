# Phase 2 — Real Money Movement via `execute()` on the Assisted Action Bridge

> ⚠️ **DO NOT ship production money movement (phase 2e / flag-on) without written legal
> sign-off that every prerequisite in [§9](#9-compliance--liability-prerequisites-the-real-gate--blocking)
> is satisfied** — KYB, sponsor-bank/FBO coverage (so we carry no money-transmitter
> licensing), returns/Reg E process, and per-user opt-in disclosures. Sandbox-only work
> (2a–2b) is fine; touching real funds before §9 clears is the failure mode that killed
> Synapse. `execute()` stays off the agent/MCP surface — the model proposes, never sends.

**Status:** Design / Not started
**Scope:** Add origination (the actual money-moving step) to the existing Bridge, behind a feature flag, human-confirmed, with a pluggable payment rail.
**Owner:** TBD
**Last updated:** 2026-06-26

---

## 0. TL;DR

The Bridge today is a **propose-and-reconcile** system: the agent computes the exact
action, the **user** executes it in their own bank, and the app verifies it happened by
observing the next Plaid sync. Everything around money movement is built — lifecycle,
two-leg reconciliation, earmark mirroring — **except the one step that originates a
payment.** The original author stubbed the socket for it: `AssistedAction.settlement_status`
exists, is documented *"RESERVED for a future originated-transfer state"*
([models.py:549](../server/src/db/models.py#L549)), and is always written `None`
([assisted_action_service.py:178](../server/src/services/assisted_action_service.py#L178)).

This doc scopes the missing piece: an `execute()` method that calls a licensed rail
(Increase for A2A sweeps, Method for debt payments), drives `settlement_status` through
`submitted → settled | failed | returned`, and converges with the existing `reconcile()`
for defense-in-depth confirmation.

**The code is ~80% of the work; the blocking 20% is non-code:** a KYB'd sponsor-bank /
rail relationship, per-account funding-source onboarding, and returns/liability handling.
**Do not start the code until the compliance prerequisites (§9) have a credible path**,
or build it flag-off against sandbox only.

---

## 1. Current state (what exists)

From [assisted_action_service.py](../server/src/services/assisted_action_service.py):

- **Lifecycle:** `propose → acknowledge → mark_done(confirmed_done) → reconcile(verified)`,
  plus `dismiss` / `expire`. ([:222–262](../server/src/services/assisted_action_service.py#L222))
- **Kinds:** `transfer`, `bill_payment`, `goal_funding`, `tax_payment`, `debt_payment`,
  `subscription_cancel`. Single-leg kinds: `bill_payment`, `tax_payment`, `debt_payment`,
  `goal_funding`. ([:58–72](../server/src/services/assisted_action_service.py#L58))
- **Reconciliation (read-only, observational):** `reconcile()` matches open Bridges against
  freshly-synced Plaid rows — two legs for `transfer`, one outflow for single-leg kinds —
  and on a match calls `_verify()`, which flips status to `verified` and mirrors any
  `how_json.goal_id` earmark into `Goal.progress` exactly once (guarded by `how['_mirrored']`).
  ([:265–420](../server/src/services/assisted_action_service.py#L265))
- **`settlement_status`:** column exists ([models.py:579](../server/src/db/models.py#L579)),
  exposed by the API ([routers/assisted_actions.py:46](../server/src/routers/assisted_actions.py#L46)),
  **only ever set to `None`.**
- **Plaid is read-only:** [plaid_client.py](../server/src/databridge/plaid_client.py) implements
  only `create_link_token`, `exchange_public_token`, webhook verification, `get_balance`,
  `sync_transactions`. No transfer/payment endpoints.

### What is missing (this doc)
1. An `execute()` origination step.
2. A `RailAdapter` abstraction + concrete adapters (Increase, Method).
3. The `settlement_status` state machine + a webhook to drive it.
4. Per-`Account` funding-source mapping (the rail's handle for each bank account).
5. Returns/failure reversal of mirrored earmarks.
6. Money-movement safety rails (caps, single-use confirmation token, MCP exclusion).

---

## 2. Goals / Non-goals

### Goals
- Originate **account-to-account ACH** for `transfer` and `goal_funding` (the tax-reserve
  sweep) via **Increase**.
- Originate **liability payments** for `debt_payment` via **Method**.
- Keep origination **human-confirmed per action**, flag-gated, fully off by default.
- Preserve the existing observational `reconcile()` as an **independent** confirmation
  (two sources of truth: the rail says it sent; Plaid says it posted).
- Idempotent: a Bridge can never be originated twice.

### Non-goals (explicitly out of scope for Phase 2)
- **Autonomous / agent-initiated** money movement. The LLM and MCP surface **never** reach
  `execute()`. The agent proposes; a separate authenticated user action executes.
- **Holding customer funds** / running our own FBO ledger / becoming a money transmitter.
  The rail + its sponsor bank are the regulated entity.
- **`tax_payment` and most `bill_payment`** auto-origination (IRS Direct Pay and many
  billers aren't cleanly originable A2A) — these **stay manual** (propose-and-reconcile) in
  Phase 2. See §6.3.
- **`subscription_cancel`** — never moved money; unchanged.

---

## 3. Architecture

### 3.1 Two orthogonal status axes
Phase 2 introduces a second status axis. Keep them separate — conflating them is the bug to avoid.

| Axis | Field | Meaning | Source of truth |
|---|---|---|---|
| **App verification** | `status` | Did we *observe* the money move? (`verified`) | Plaid sync (`reconcile`) **and/or** rail settlement |
| **Rail settlement** | `settlement_status` | Did the *rail* accept/settle/return the origination? | Rail webhook |

A user-manual Bridge (today's behavior) has `settlement_status = None` forever and reaches
`verified` only via Plaid observation. An **app-originated** Bridge moves through
`settlement_status` and can reach `verified` via **either** the rail confirming settlement
**or** Plaid observing the posted row — whichever comes first (idempotent mirror).

### 3.2 `settlement_status` state machine

```
                 execute() success
   None ───────────────────────────────▶ submitted
   (manual /                                  │
    not yet                     rail webhook  │
    originated)         ┌──────────────┬──────┴───────┐
                        ▼              ▼              ▼
                     settled         failed        returned
                   (money moved)  (never left)  (came back, Reg E /
                        │                         NSF / R-code)
                        │                              │
              may trigger _verify              REVERSE mirrored
              (+ mirror earmark)               earmark if already
                                               mirrored; notify user
```

- `None` → `submitted`: only `execute()` sets this, exactly once.
- `submitted` → `settled` / `failed` / `returned`: only the **webhook handler** sets these.
- ACH returns can arrive **days after** `settled` (R01 NSF, R10 unauthorized…). So `settled`
  is **not terminal** for ~5 business days; a later `returned` must reverse the earmark.
  This is the single most important correctness constraint in Phase 2.

### 3.3 Rail adapter abstraction

A thin interface so kinds map to rails without `execute()` knowing provider details.

```python
# services/rails/base.py
class RailError(Exception): ...

@dataclass(frozen=True)
class OriginationResult:
    rail: str                 # "increase" | "method"
    rail_ref: str             # provider transfer/payment id
    settlement_status: str    # "submitted" (or "settled" for instant rails)

class RailAdapter(Protocol):
    name: str
    def originate(
        self,
        *,
        amount_cents: int,
        source: FundingSource,        # resolved rail handle for the paying account
        dest: FundingDest,            # rail handle (A2A) or liability target (Method)
        idempotency_key: str,         # MUST be stable per Bridge (see §4.3)
        memo: str,                    # ≤ rail's max; e.g. "Tax reserve"
    ) -> OriginationResult: ...
```

- `IncreaseAdapter` → `POST /transfers/ach` (originate ACH credit/debit between the user's
  own linked accounts). Flat $0.50 next-day. Bank-direct (First Internet Bank / Blue Ridge),
  so no MTL on us. Idempotency via Increase's `Idempotency-Key` header.
- `MethodAdapter` → `POST /payments` (source = our corporate ACH funding account; dest =
  Method liability id). Method stays out of our flow of funds; it carries the transmitter
  posture.

Rail selection (pure mapping, no branching in `execute()`):

```python
_RAIL_FOR_KIND = {
    "transfer":     "increase",   # A2A, user's own accounts
    "goal_funding": "increase",   # sweep into a savings/goal account
    "debt_payment": "method",     # pay a liability
    # bill_payment / tax_payment: no auto-rail in Phase 2 → stay manual
}
ORIGINABLE_KINDS = frozenset(_RAIL_FOR_KIND)
```

---

## 4. The `execute()` method

### 4.1 Where it slots in
Between `mark_done` and `reconcile` in the lifecycle. The **new** happy path for an
originable, rail-enabled Bridge:

```
propose → acknowledge → execute() ──submitted──▶ webhook ──settled──▶ verified (+mirror)
                                          │                  ▲
                                          └── reconcile() ───┘  (independent Plaid confirm)
```

Manual path (unchanged, fallback, and the only path for non-originable kinds):
```
propose → acknowledge → mark_done → reconcile → verified
```

### 4.2 Signature (matches the file's style)

```python
def execute(
    self,
    user_id: int,
    action_id: int,
    *,
    rail: RailAdapter,
    confirmation_token: str,        # single-use, short-TTL, minted at user confirm (§7)
    caps: SpendCaps,                # per-txn / daily / velocity (§7)
    funding: FundingResolver,       # Account.id → rail FundingSource/Dest (§5)
    today: Optional[date] = None,
) -> AssistedActionORM:
    """Originate the real-world money movement for an eligible Bridge.

    Idempotent and guard-railed. Sets ``settlement_status='submitted'`` and stores the
    rail reference; NEVER sets ``status='verified'`` (that stays with settlement webhook
    and/or reconcile, R2 — the app trusts observation/settlement, not its own request).
    """
```

### 4.3 Flow & guards (in order — all must pass before any rail call)

1. **Ownership:** `bridge = self._own(user_id, action_id)` ([:211](../server/src/services/assisted_action_service.py#L211)).
2. **Kind eligible:** `bridge.kind in ORIGINABLE_KINDS` else `RailError`.
3. **Status gate:** `bridge.status in ("acknowledged", "confirmed_done")`. Not `proposed`
   (user hasn't engaged), not a resolved state.
4. **Idempotency / no double-originate:** `bridge.settlement_status is None`. If already
   `submitted`/`settled`, return the bridge unchanged (replay-safe).
5. **Fresh human confirmation:** `confirmation_token` validates for *this* `action_id` and
   *this* amount, is unused, and is within TTL. (Minted only by an authenticated user
   endpoint — never by the agent/MCP. §7.)
6. **Caps:** `amount_cents` ≤ per-txn cap; rolling daily/velocity within limits. Else raise.
7. **Funding resolution:** resolve `source_ref`/`dest_ref` (internal `Account.id`s) to rail
   handles via `funding`. If either side lacks a rail funding source → raise (origination
   impossible; fall back to manual). External-label dests (IRS) are already non-originable.
8. **Idempotency key:** reuse the Bridge's stable `verify_ref` as the rail idempotency key
   (it already encodes user+kind+amount+accounts+day, [:186–208](../server/src/services/assisted_action_service.py#L186)).
   This guarantees a retried `execute()` can't double-send at the rail either.
9. **Originate:** `result = rail.originate(...)` inside try/except → on `RailError`, leave
   `settlement_status=None`, record the error, surface to user, **do not** advance status.
10. **Persist:** `bridge.settlement_status = result.settlement_status` (`submitted`);
    store `bridge.rail = result.rail`, `bridge.rail_ref = result.rail_ref`; `flush()`.
11. **Audit log** the origination (§7).

> `execute()` does **not** mirror the earmark and does **not** set `verified`. Mirroring
> happens only on confirmed settlement, reusing the existing `_verify()` /`_mirrored` guard.

### 4.4 Settlement webhook handler (new)

```python
def apply_settlement(self, rail: str, rail_ref: str, event: str) -> Optional[AssistedActionORM]:
    """Drive settlement_status from a verified rail webhook. event ∈
    {settled, failed, returned}. Idempotent per (rail_ref, event)."""
```

- Look up the Bridge by `(rail, rail_ref)`.
- `settled` → set `settlement_status='settled'`; call `_verify(bridge)` (mirrors earmark
  once). For A2A internal transfers that Plaid will *also* show, `reconcile()` later is a
  no-op because the Bridge is already resolved — fine.
- `failed` → `settlement_status='failed'`; notify user; bridge returns to actionable (manual
  fallback offered). No earmark was mirrored, nothing to reverse.
- `returned` → `settlement_status='returned'`; **if `how['_mirrored']`, subtract the amount
  back out of `Goal.progress`** and clear the flag; notify user (Reg E / NSF copy).
- Verify the webhook signature; ignore unknown refs; dedupe on event id.

---

## 5. Data model changes

### 5.1 `AssistedAction` (add columns)
```python
rail:            Mapped[Optional[str]]   # "increase" | "method"  (NULL = manual)
rail_ref:        Mapped[Optional[str]]   # provider transfer/payment id (indexed)
settlement_detail_json: Mapped[Optional[str]]  # return R-codes, failure reason, ts
```
`settlement_status` already exists. Add a unique index on `(rail, rail_ref)` for webhook lookup.

### 5.2 Funding-source mapping (new)
Origination needs the rail's handle for each bank account. The user's `Account` is linked via
Plaid; the rail needs a **Plaid processor token** minted for that account and exchanged into a
rail funding source.

```python
class RailFundingSource(Base):
    id: int
    user_id: int            # RLS tenant column (see db/rls.py)
    account_id: int         # FK → Account.id
    rail: str               # "increase" | "method"
    external_id: str        # Increase account_number_id / Method account id
    status: str             # "active" | "pending" | "revoked"
```
Onboarding flow (one-time per account): Plaid Link (already have) → `/processor/token/create`
for the rail → rail account-create → store `external_id`. This is its own mini-epic; gate
`execute()` on an `active` funding source existing.

---

## 6. Per-feature mapping

### 6.1 Tax-reserve sweep (`transfer` / `goal_funding`) → Increase
- Amount comes from the existing income-smoothing / tax-reserve math (already computed).
- Source = user's checking `Account.id`; dest = user's **own** linked savings `Account.id`.
- Rail: Increase ACH, $0.50 flat next-day. **Batch** (Acorns' $5-threshold lesson) — don't
  originate sub-$X sweeps; accumulate as a virtual earmark and sweep on threshold/schedule.
- Verification: dual — Increase `settled` webhook **and** Plaid sees both legs. Either resolves.

### 6.2 Debt-"boss" payment (`debt_payment`) → Method
- Source = our corporate funding account (Method model); dest = Method liability id for the
  user's card/loan (Method discovers it; no account number needed).
- Maps 1:1 onto the boss HP mechanic — a `settled` payment is real principal reduction.
- Verification: Method payment webhook is authoritative (the creditor leg isn't in the user's
  Plaid as a clean A2A credit). `reconcile()`'s single-leg outflow match is a secondary check.

### 6.3 `bill_payment` / `tax_payment` → stay MANUAL in Phase 2
- IRS Direct Pay and most billers aren't cleanly originable A2A; auto-paying them adds
  licensing/biller-network scope we don't want yet. Keep propose-and-reconcile. Revisit in
  Phase 3 (Method bill-pay covers *some* billers).

### 6.4 `subscription_cancel` → unchanged
Never touched money; `verify_cancellation()` (absence-based) stays as-is.

---

## 7. Safety (money movement is a different threat model)

- **Agent/MCP exclusion:** `execute()` is callable **only** from an authenticated user
  endpoint. It is **not** an assistant tool and **not** on the MCP surface (which stays the
  8 read-only tools). The agent's `propose_assisted_action` is unchanged — propose only.
  This is the prompt-injection / lethal-trifecta firewall: the model can suggest, never send.
- **Single-use confirmation token:** minted server-side when the user taps "Send it" on a
  specific Bridge; bound to `(action_id, amount_cents)`, short TTL, consumed on `execute()`.
  Re-tapping mints a new one; a stale/replayed token is rejected.
- **Hard caps (config-gated, user-set under a system max):** per-transaction, rolling daily
  total, and per-window velocity. Caps live next to the existing `users.s2s_*` config.
- **Forecast veto reuse:** before originating a sweep, reuse the existing forecast veto
  pattern (behavioral.py F2) — never originate a sweep that pushes the month negative.
- **Audit trail:** append-only log of every origination attempt (who, when, amount, rail,
  ref, outcome) — the discipline Synapse skipped. Reconcile this daily against the rail.
- **Returns reversal:** the `returned` path (§4.4) must always be able to undo a mirror.

---

## 8. Failure modes & edge cases

| Case | Handling |
|---|---|
| `execute()` retried (network/double-tap) | Guard on `settlement_status is None` + rail idempotency key (`verify_ref`) → at most one origination. |
| Rail accepts then ACH returns (R01/R10) days later | `settled`→`returned` webhook reverses mirrored earmark; user notified; Bridge actionable again. |
| Rail `settled` but Plaid never shows the row | For app-originated, rail settlement is sufficient to `verify`; reconcile is a bonus, not required. |
| Plaid shows the row before the webhook | `reconcile()` verifies + mirrors first; later `settled` webhook is idempotent (already resolved). |
| Funding source missing/revoked | `execute()` raises pre-call; UI falls back to manual "do it in your bank." |
| Amount over cap / forecast veto | Raise before any rail call; nothing originated. |
| External-dest transfer (IRS, "your bank") | `_as_account_id` returns None → non-originable → manual only (already true). |
| User dismisses after `submitted` | Cannot un-send; dismiss only hides the card. Status reflects real settlement; document this clearly in UI. |

---

## 9. Compliance / liability prerequisites (THE REAL GATE — blocking)

None of the code in §4–§6 should touch production money until these exist. (Per the rail
research and the Catch/Synapse post-mortems, this is what kills builders, not the UI.)

1. **Business entity + KYB** with Increase and/or Method.
2. **Sponsor-bank / FBO coverage so we carry no MTL** — confirmed in writing per rail. (FBO
   ≠ automatic exemption; it's control-dependent and state-by-state — get the rail's counsel
   position.)
3. **Per-account funding-source onboarding** (Plaid processor token → rail) live.
4. **Returns/NSF + Reg E process:** who eats unauthorized-return loss; dispute SLA; the
   reversal flow (§4.4) tested.
5. **Volume/pricing reality:** confirm no minimum that sinks a low-volume start (Increase has
   no public minimum but KYBs you; avoid $250–$5,000/mo BaaS tiers).
6. **Money-moving feature flag** default-OFF, per-user opt-in, with explicit disclosures.

---

## 10. Rollout (flag-gated, incremental)

- **2a — Skeleton (sandbox only):** `RailAdapter` interface + `IncreaseAdapter` against
  Increase sandbox; `execute()` with all guards; `settlement_status` writes; **no real funds**.
  Unit tests for guards + idempotency. Flag off.
- **2b — Settlement loop:** webhook router + `apply_settlement` + returns reversal +
  earmark-mirror convergence with `reconcile()`. Sandbox webhooks.
- **2c — Funding onboarding:** `RailFundingSource` + Plaid processor-token flow.
- **2d — Method / debt:** `MethodAdapter` + `debt_payment` path.
- **2e — Production pilot:** only after §9. One feature (sweep *or* debt), tiny caps, opt-in,
  daily rail reconciliation, monitored.

---

## 11. Testing

- **Guards:** each §4.3 guard rejects correctly (wrong kind, wrong status, double-execute,
  stale token, over-cap, missing funding).
- **Idempotency:** two `execute()` calls + two identical webhooks → one origination, one mirror.
- **Settlement convergence:** webhook-first vs Plaid-first both reach `verified` exactly once.
- **Returns:** `settled`→`returned` reverses the earmark to the cent; never goes negative.
- **Webhook security:** bad signature rejected; unknown `rail_ref` ignored.
- **Determinism:** keep the file's seeded/`today`-injected style (no `Date.now()` in logic).
- Reuse the existing PG + SQLite test harness (`./.venv/bin/python -m pytest`).

---

## 12. Open decisions

1. **First rail/feature:** Increase + tax-sweep (A2A, friendliest ACH profile) **or** Method +
   debt (best wedge, out of flow of funds). Recommendation: **Increase + sweep first** (lower
   liability surface, fully your-own-accounts), Method second.
2. **Auto-verify on settlement vs require Plaid confirmation** for A2A — recommend allow rail
   `settled` to verify (with reconcile as redundant confirm) to avoid hanging on invisible legs.
3. **Funding-source storage**: dedicated `RailFundingSource` table (recommended) vs columns on
   `Account`.
4. **Batch policy** for sweeps (threshold $ and/or cadence) — product decision.

---

## 13. Effort estimate (engineering only; excludes §9 compliance)

| Slice | Rough size |
|---|---|
| 2a skeleton + guards + tests (sandbox) | M |
| 2b settlement webhook + returns reversal | M |
| 2c funding-source onboarding | M–L |
| 2d Method adapter + debt path | M |
| 2e prod hardening (audit, caps, reconcile job) | M |

The compliance/onboarding track (§9) runs in **parallel and is the critical path** — it is
months of relationship/underwriting work, not engineering. Build 2a–2b against sandbox now if
desired; do not ship 2e until §9 clears.
