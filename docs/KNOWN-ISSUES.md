# Known Issues

Deliberate, documented deviations — behaviors that look like bugs but are held by
decision. Recorded so they aren't "fixed" by accident later. See
`docs/AUDIT-FIXES-LATER.md` for the full deferred backlog.

---

## KI-1 — Credit-card / loan balances stored as `available` (M8 / audit L7) · HELD

**Behavior.** When an account is linked or refreshed, we store
`balances.available` uniformly for **every** account type
(`server/src/routers/plaid.py` exchange path; `server/src/services/plaid_service.py`
`_refresh_balances`). For `depository` accounts `available` is money you have. For
`credit` and `loan` accounts, Plaid's `available` is **remaining credit / available
borrowing power**, not a positive asset.

**Consequence.** A credit card with a $4,000 available limit is counted as +$4,000,
inflating **net worth** and **Safe-to-Spend** rather than showing the debt as a
liability.

**Status — HELD by the product owner.** Leaving balances as-is for now avoids an
immediate net-worth shift for existing users and the data backfill that a correct
treatment requires. This is a **known limitation**, not a bug to be silently
patched.

**Future fix (when un-held).**
- Branch on `account["type"]`: store `current` as a **negated liability** for
  `credit`/`loan`; keep `available` for `depository`.
- Apply the **same** rule in BOTH the exchange path and the refresh path (today the
  exchange path defaults a missing balance to `0` while refresh **skips** on
  `value is None` — unify that too).
- One-time, **reversible** backfill migration to re-sign existing rows.
- Audit `networth_service` and the Safe-to-Spend aggregation so liabilities carry
  the correct sign everywhere they're summed.

---

## KI-2 — Plaid webhooks are additive; pre-existing items need a re-link · INFO

Inbound Plaid webhooks (audit L1) route by `item_id`, stored on `Token.item_id`,
which is only populated at link/exchange time going forward. Items linked before
the webhook work shipped have a NULL `item_id` and will not receive webhook-driven
syncs until they are re-linked (or pushed the new webhook URL via
`item/webhook/update`, a noted follow-up). Polling + the re-link notice (NOW B4)
continue to cover those items, so this is a coverage gap, not a correctness bug.
