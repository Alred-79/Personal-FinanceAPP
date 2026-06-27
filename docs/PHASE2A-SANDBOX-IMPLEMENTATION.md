# Phase 2a–2b — Sandbox Origination Skeleton (Buildable Today)

> ✅ **Safe to build now.** Everything in this doc is **flag-off, sandbox-only, no real
> funds.** It has **zero dependency on the §9 compliance gate** in
> [PHASE2-ASSISTED-ACTION-EXECUTE-DESIGN.md](./PHASE2-ASSISTED-ACTION-EXECUTE-DESIGN.md).
> A new master flag `rail_origination_enabled` ships **default `False`**; with it off, the
> app behaves exactly as today. **Do not enable in production** — the only legal target for
> these adapters is the rail's *sandbox* environment.

**Parent design:** [PHASE2-ASSISTED-ACTION-EXECUTE-DESIGN.md](./PHASE2-ASSISTED-ACTION-EXECUTE-DESIGN.md)
**Scope here:** Rollout slices **2a** (origination skeleton + guards) and **2b** (settlement
webhook + returns reversal), against **Increase sandbox only**.
**Out of scope here:** 2c funding onboarding, 2d Method/debt, 2e production — and all of §9.
**Last updated:** 2026-06-26

---

## 0. Why this is safe to build

- The flag `rail_origination_enabled` defaults `False` ([settings.py](../server/src/settings.py)
  follows the existing `*_enabled: bool = False` convention, e.g. `auditor_enabled`,
  `merchant_lifecycle_enabled`, `tax_features_enabled`).
- With the flag off, `execute()` is **never callable** — the endpoint 404/403s and the method
  raises before any rail call.
- Adapters point only at the rail **sandbox base URL**. There is no production credential path
  in this slice.
- `execute()` is **not** an assistant tool and **not** on the MCP surface (which stays the 8
  read-only tools). The agent's `propose_assisted_action` is unchanged.
- No real money can move: sandbox rails settle fake transfers; Plaid stays read-only.

---

## 1. Pre-flight (read these first)

| File | Why |
|---|---|
| [services/assisted_action_service.py](../server/src/services/assisted_action_service.py) | Lifecycle (`propose`/`acknowledge`/`mark_done`/`reconcile`), `_own`, `_verify`, `_mirrored` guard, `verify_ref`/`_default_verify_ref`, `_SINGLE_LEG_KINDS`. `execute()` slots in here. |
| [db/models.py:538–579](../server/src/db/models.py#L538) | `AssistedAction`; `settlement_status` already exists (line 579, RESERVED). Add `rail`, `rail_ref`, `settlement_detail_json`. |
| [routers/assisted_actions.py](../server/src/routers/assisted_actions.py) | `_to_dict` (line 32) already serializes `settlement_status`; `_transition` (line 63) is the endpoint pattern to copy. |
| [settings.py](../server/src/settings.py) | Add `rail_origination_enabled` + sandbox config. |
| [server/migrations/versions/](../server/migrations/versions/) | Alembic; add one migration for the new columns. Watch the migration-id-collision gotcha (use a fresh hash, set `down_revision` to current head). |
| [server/tests/test_assisted_action.py](../server/tests/test_assisted_action.py) | Extend with guard/idempotency/settlement tests. |

Run tests with: `./.venv/bin/python -m pytest server/tests/test_assisted_action.py -q`
(no pipenv; see project test-invocation note).

---

## 2. Build order (each step is independently mergeable, flag-off)

### Step 1 — Settings flag + sandbox config
[settings.py](../server/src/settings.py), in `class Settings(BaseSettings)`:
```python
# --- Rail origination (Phase 2a, SANDBOX ONLY; see docs/PHASE2A-SANDBOX-IMPLEMENTATION.md)
# Master switch. Default OFF. Production enablement is gated on the §9 compliance track
# in PHASE2-ASSISTED-ACTION-EXECUTE-DESIGN.md and MUST NOT be flipped on without legal sign-off.
rail_origination_enabled: bool = False
increase_sandbox_base_url: str = "https://sandbox.increase.com"
increase_sandbox_api_key: str = ""          # sandbox key only; empty in CI
increase_webhook_secret: str = ""           # for HMAC verification of sandbox webhooks
rail_per_txn_cap_cents: int = 50_000        # $500 hard ceiling in sandbox
rail_daily_cap_cents: int = 100_000         # $1000/day
```
**Test:** a config test asserts the default is `False` and the base URL is the sandbox host.

### Step 2 — Data model + migration
[db/models.py](../server/src/db/models.py) on `AssistedAction`:
```python
rail:                   Mapped[Optional[str]] = mapped_column(String, nullable=True)   # "increase" | "method"
rail_ref:               Mapped[Optional[str]] = mapped_column(String, nullable=True)   # provider id
settlement_detail_json: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # R-codes / failure reason / ts
```
- `settlement_status` already exists — **do not re-add it.**
- Migration: add the 3 columns + a **unique index on `(rail, rail_ref)`** (webhook lookup).
  Both columns nullable, so existing rows backfill as NULL = "manual" — no data change.
- Serialize the new fields in [routers/assisted_actions.py `_to_dict`](../server/src/routers/assisted_actions.py#L32).
- **Test:** model round-trips the columns; `_to_dict` includes them.

### Step 3 — Rail adapter abstraction
New package `server/src/services/rails/`:
```
rails/
  __init__.py
  base.py        # RailError, OriginationResult, FundingSource/Dest, RailAdapter Protocol
  increase.py    # IncreaseAdapter → sandbox POST /transfers/ach
```
`base.py` — exactly the Protocol from the parent design §3.3 (`originate(...) -> OriginationResult`,
`OriginationResult(rail, rail_ref, settlement_status)`, `RailError`).

`increase.py` — `IncreaseAdapter`:
- Reads `increase_sandbox_base_url` / `increase_sandbox_api_key` from settings.
- `originate()` → `POST /transfers/ach` with the `Idempotency-Key` header set to the Bridge's
  `verify_ref` (stable per intent — already encodes user+kind+amount+accounts+day).
- Maps HTTP/network failure → `RailError` (never leaks a half-state).
- Returns `OriginationResult(rail="increase", rail_ref=<id>, settlement_status="submitted")`.
- **Test:** a `FakeRail` (in-memory, records calls, can be told to raise / return a ref) is the
  primary test double — **no live sandbox call in unit tests.** Optionally one `@pytest.mark`-gated
  integration test that hits real sandbox, skipped when `increase_sandbox_api_key` is empty.

Rail selection mapping (parent §3.3):
```python
_RAIL_FOR_KIND = {"transfer": "increase", "goal_funding": "increase"}  # debt_payment/Method deferred to 2d
ORIGINABLE_KINDS = frozenset(_RAIL_FOR_KIND)
```

### Step 4 — `execute()` on the service (the core of 2a)
[assisted_action_service.py](../server/src/services/assisted_action_service.py), new method slotting
between `mark_done` and `reconcile`. Signature per parent §4.2. **Guards in order — every one must
pass before any rail call** (parent §4.3):

1. **Flag:** `rail_origination_enabled` is `True`, else `RailError` (belt-and-suspenders; the
   endpoint also guards).
2. **Ownership:** `bridge = self._own(user_id, action_id)`.
3. **Kind eligible:** `bridge.kind in ORIGINABLE_KINDS`.
4. **Status gate:** `bridge.status in ("acknowledged", "confirmed_done")`.
5. **Idempotency:** `bridge.settlement_status is None`; if already `submitted`/`settled`, return
   the bridge unchanged (replay-safe — no exception).
6. **Confirmation token:** validates for *this* `action_id` + amount, unused, within TTL.
   (In 2a the token can be a minimal HMAC over `(action_id, amount_cents, nonce)` reusing the
   existing token-family HKDF in [settings.py](../server/src/settings.py); full UX in 2c.)
7. **Caps:** `amount_cents ≤ rail_per_txn_cap_cents`; rolling daily ≤ `rail_daily_cap_cents`.
8. **Funding resolution:** in 2a, a `FundingResolver` Protocol resolves `Account.id → handle`.
   Until 2c onboarding exists, the resolver is a **stub that raises** for any account without a
   sandbox handle → `execute()` falls back to manual. (This is correct: no funding source yet.)
9. **Originate:** `result = rail.originate(...)` in try/except → on `RailError`, leave
   `settlement_status=None`, write `settlement_detail_json` error, **do not** advance.
10. **Persist:** `settlement_status="submitted"`, `rail`, `rail_ref`; `flush()`.
11. **Audit log** the attempt (who/when/amount/rail/ref/outcome).

> `execute()` **never** sets `status="verified"` and **never** mirrors the earmark. Mirroring
> stays with settlement/`reconcile`, reusing the existing `_verify()` / `how['_mirrored']` guard.

### Step 5 — Settlement webhook + returns reversal (the core of 2b)
- New `apply_settlement(self, rail, rail_ref, event)` per parent §4.4. `event ∈ {settled, failed,
  returned}`. Look up by `(rail, rail_ref)`; idempotent per `(rail_ref, event)`.
  - `settled` → `settlement_status="settled"`; call existing `_verify(bridge)` (mirrors once via
    `_mirrored`).
  - `failed` → `settlement_status="failed"`; nothing mirrored, nothing to reverse; bridge
    actionable again.
  - `returned` → `settlement_status="returned"`; **if `how['_mirrored']`, subtract the amount back
    out of `Goal.progress` and clear the flag**; record R-code in `settlement_detail_json`.
- New webhook endpoint (its own router or in [routers/assisted_actions.py](../server/src/routers/assisted_actions.py)):
  verify HMAC signature against `increase_webhook_secret`, dedupe on event id, ignore unknown refs.
- **Convergence:** if Plaid's `reconcile()` resolves the Bridge first, a later `settled` webhook is
  a no-op (already resolved); if the webhook resolves first, later `reconcile()` is a no-op. Both
  reach `verified` exactly once.

### Step 6 — `execute()` endpoint (flag-gated)
New `POST /assisted-actions/{action_id}/execute/` mirroring the [`_transition`](../server/src/routers/assisted_actions.py#L63)
pattern but:
- 404/403 when `rail_origination_enabled` is `False`.
- Requires the authenticated user (same auth dep as the other endpoints).
- Accepts the confirmation token; calls `service.execute(...)`.
- **Not** added to any assistant/MCP tool registry.

---

## 3. Test matrix (extend [test_assisted_action.py](../server/tests/test_assisted_action.py))

| Test | Asserts |
|---|---|
| flag default off | `Settings().rail_origination_enabled is False`; sandbox base URL |
| flag gate | `execute()` raises / endpoint 404s when flag off |
| each guard rejects | wrong kind, wrong status, double-execute, stale token, over per-txn cap, over daily cap, missing funding source |
| idempotency | two `execute()` calls → one `originate()` call (FakeRail records 1), one `submitted` |
| origination failure | `RailError` leaves `settlement_status=None`, status unchanged, detail recorded |
| webhook `settled` | mirrors earmark once (`_mirrored` set); second identical webhook is no-op |
| webhook `returned` after `settled` | reverses `Goal.progress` to the cent; never negative; flag cleared |
| convergence: Plaid first | `reconcile()` verifies+mirrors; later `settled` webhook no-op |
| convergence: webhook first | `settled` verifies+mirrors; later `reconcile()` no-op |
| webhook security | bad HMAC rejected; unknown `rail_ref` ignored |
| MCP exclusion | `execute` not present in the MCP tool list / assistant tool registry |
| determinism | `today` injected; no `Date.now()` equivalent in logic |

Run full suite on both backends before merge (PG + SQLite): `./.venv/bin/python -m pytest -q`.

---

## 4. Definition of done (2a–2b)

- [ ] `rail_origination_enabled` defaults `False`; suite green with flag off = today's behavior.
- [ ] Migration applies clean on SQLite **and** Postgres; `(rail, rail_ref)` unique index present.
- [ ] `RailAdapter` + `IncreaseAdapter` (sandbox) + `FakeRail` test double.
- [ ] `execute()` with all 11 guards; idempotent; never sets `verified`; never mirrors.
- [ ] `apply_settlement` + webhook endpoint; returns-reversal proven to the cent.
- [ ] `execute` endpoint flag-gated; absent from MCP/assistant surface.
- [ ] Full test matrix green on PG + SQLite.
- [ ] **No production credentials anywhere; no real funds moved.**

When all boxes are checked, 2a–2b are complete and the design is validated in code — while the
§9 compliance/onboarding track (the real blocker for ever shipping 2e) runs in parallel.

---

## 5. Explicitly NOT in this slice

- §9 compliance (KYB, sponsor bank, MTL posture, Reg E) — none of it.
- 2c funding-source onboarding (Plaid processor token → rail) — `FundingResolver` is a raising stub here.
- 2d Method adapter / `debt_payment`.
- 2e production hardening / enabling the flag in prod.
- `bill_payment` / `tax_payment` origination (stay manual; parent §6.3).

Touching any of the above means leaving "buildable today" — stop and return to the parent design.
