"""Liability CRUD + reconciliation (v4 package 06).

The ONLY writer to the ``liabilities`` / ``liability_adjustments`` tables. Fold
handlers never touch these tables — they project ``boss_state`` from the event
log; this service owns the truth-adjacent mutations.

Concentration rule: at most one ``is_active_boss`` per user. A defeated liability
is permanent — its status can never transition back to active.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import Liability, LiabilityAdjustment
from ...models import UserInDB

ACTIVE = "active"
DORMANT = "dormant"
DEFEATED_SEALED = "defeated_sealed"
DEFEATED_BANISHED = "defeated_banished"
_DEFEATED = {DEFEATED_SEALED, DEFEATED_BANISHED}

KINDS = {"credit_card", "loan", "bnpl", "other"}


class LiabilityError(Exception):
    """Raised on an invalid liability operation (e.g. resurrecting a defeat)."""


class LiabilityService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── CRUD ──────────────────────────────────────────────────────────────

    def create(
        self,
        user: UserInDB,
        *,
        name: str,
        kind: str = "credit_card",
        principal_cents: int = 0,
        apr_bps: int = 0,
        minimum_payment_cents: int = 0,
        due_day: Optional[int] = None,
        linked_account_id: Optional[int] = None,
        linked_plaid_account: Optional[str] = None,
    ) -> Liability:
        if kind not in KINDS:
            raise LiabilityError(f"unknown liability kind: {kind!r}")
        liab = Liability(
            user_id=user.id,
            name=name,
            kind=kind,
            principal_cents=principal_cents,
            apr_bps=apr_bps,
            minimum_payment_cents=minimum_payment_cents,
            due_day=due_day,
            linked_account_id=linked_account_id,
            linked_plaid_account=linked_plaid_account,
            status=ACTIVE,
        )
        self.db.add(liab)
        self.db.flush()
        return liab

    def get(self, user: UserInDB, liability_id: int) -> Optional[Liability]:
        return self.db.execute(
            select(Liability).where(
                Liability.id == liability_id, Liability.user_id == user.id
            )
        ).scalar_one_or_none()

    def list(self, user: UserInDB) -> list[Liability]:
        return list(
            self.db.execute(
                select(Liability).where(Liability.user_id == user.id).order_by(
                    Liability.principal_cents.asc()
                )
            ).scalars()
        )

    # ── the one active boss (concentration) ───────────────────────────────

    def active_boss(self, user: UserInDB) -> Optional[Liability]:
        return self.db.execute(
            select(Liability).where(
                Liability.user_id == user.id, Liability.is_active_boss == 1
            )
        ).scalar_one_or_none()

    def set_active_boss(self, user: UserInDB, liability_id: int) -> Liability:
        """Make one liability the active boss. Blocks if another is active
        (one-active enforcement) — the caller surfaces a 409."""
        current = self.active_boss(user)
        if current is not None and current.id != liability_id:
            raise LiabilityError("another boss is already active")
        liab = self.get(user, liability_id)
        if liab is None:
            raise LiabilityError("liability not found")
        if liab.status in _DEFEATED:
            raise LiabilityError("cannot activate a defeated boss")
        liab.is_active_boss = 1
        self.db.flush()
        return liab

    def default_boss_order(self, user: UserInDB) -> list[Liability]:
        """Smallest-balance-first (snowball) default ordering of active debts."""
        return [
            liability
            for liability in self.list(user)
            if liability.status not in _DEFEATED
        ]

    # ── reconciliation (never a silent edit) ──────────────────────────────

    def reconcile(
        self, user: UserInDB, liability_id: int, observed_cents: int, reason: str = ""
    ) -> LiabilityAdjustment:
        """Record an adjustment for the drift between derived and observed
        balance. Appends a row; does NOT silently rewrite principal_cents."""
        liab = self.get(user, liability_id)
        if liab is None:
            raise LiabilityError("liability not found")
        delta = observed_cents - liab.principal_cents
        adj = LiabilityAdjustment(
            liability_id=liab.id, delta_cents=delta, reason=reason or "reconcile"
        )
        self.db.add(adj)
        self.db.flush()
        # The whole point of a reconcile is to correct displayed balance drift, so
        # the drift must reach boss HP. Emit a BossCorrected with the signed delta
        # (observed − derived): a positive delta means the real balance is higher
        # than the boss thinks, so HP rises. Idempotent on the adjustment id.
        if delta != 0:
            from .events import GameEventDraft, record_events

            record_events(self.db, [GameEventDraft(
                stream=f"boss:{liab.id}", type="BossCorrected",
                payload={"liability_id": liab.id, "hp_delta": delta},
                idempotency_key=f"reconcile:{liab.id}:{adj.id}",
            )])
            self.db.flush()
        return adj

    # ── closure (permanent) ────────────────────────────────────────────────

    def close(self, user: UserInDB, liability_id: int, *, sealed: bool) -> Liability:
        """Seal (close account) or banish (keep open at zero) a defeated boss.

        Permanent: a liability already in a defeated status cannot be closed
        again or reopened (test 13)."""
        liab = self.get(user, liability_id)
        if liab is None:
            raise LiabilityError("liability not found")
        if liab.status in _DEFEATED:
            raise LiabilityError("liability already defeated — defeat is permanent")
        liab.status = DEFEATED_SEALED if sealed else DEFEATED_BANISHED
        liab.is_active_boss = 0
        liab.defeated_at = datetime.now(timezone.utc)
        self.db.flush()
        return liab

    @staticmethod
    def to_dict(liab: Liability) -> dict:
        return {
            "id": liab.id,
            "name": liab.name,
            "kind": liab.kind,
            "principal_cents": liab.principal_cents,
            "apr_bps": liab.apr_bps,
            "minimum_payment_cents": liab.minimum_payment_cents,
            "due_day": liab.due_day,
            "status": liab.status,
            "is_active_boss": bool(liab.is_active_boss),
            "ordering_choice": liab.ordering_choice,
        }
