"""The Detangler — make spending numbers TRUE by relating existing transactions.

Naive transaction lists double-count and mislead:

* a **transfer** between the user's own accounts looks like a big expense AND a
  big income, polluting spend totals,
* a **refund** sits as a lone positive that should cancel an earlier purchase,
* a **duplicate** (the same charge arriving via Plaid *and* a manual entry *and*
  a statement import) inflates everything.

This service runs over ALL of a user's transactions — however they arrived — and
flags these relationships using the same ``matching`` engine the import dedup
uses. It is deliberately conservative: it never deletes or merges money on its
own. It raises a deduplicated ``Notification`` per pairing (stable ``ref`` so a
re-run doesn't spam), and the user resolves each one. The collapse itself would
go through the existing propose→confirm path — surfacing, not silent edits.

Runs from two triggers: an on-demand endpoint (``POST /imports/detangle/run/``)
and a daily scheduler job, mirroring ``job_check_plan_drift``.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Account as AccountORM
from ..db.models import Expense as ExpenseORM
from ..db.models import Income as IncomeORM
from ..db.models import Notification as NotificationORM
from ..money import cents_to_dollars
from .matching import MatchRow, Pairing, find_pairings

# A transfer/refund window a little wider than the import-dedup default: a
# transfer can take a couple of business days to land in the other account, and
# refunds settle slower still. Conservative enough to avoid false pairs.
DETANGLE_WINDOW_DAYS = 5

_KIND_COPY = {
    "transfer": (
        "Possible transfer",
        "“{a}” and “{b}” look like a transfer between your accounts "
        "(${amount:.2f}). Linking them keeps it out of your spending totals.",
    ),
    "refund": (
        "Possible refund",
        "A ${amount:.2f} credit “{b}” looks like a refund of “{a}”. "
        "Want to link them?",
    ),
    "duplicate": (
        "Possible duplicate",
        "“{a}” and “{b}” (${amount:.2f}) look like the same transaction "
        "recorded twice.",
    ),
}


class DetangleService:
    """Find transfer / refund / duplicate pairs and surface them as notifications."""

    def __init__(self, db: Session, *, window_days: int = DETANGLE_WINDOW_DAYS) -> None:
        self.db = db
        self.window_days = window_days

    def run(self, user_id: int) -> list[NotificationORM]:
        """Detangle one user's transactions. Returns the notifications created.

        Idempotent per pairing via a stable ``ref`` — a re-run that re-finds the
        same pair adds nothing. Returns only the *new* notifications so callers
        can count real work done.
        """
        rows = self._all_match_rows(user_id)
        pairings = find_pairings(rows, self.window_days)
        created: list[NotificationORM] = []
        for p in pairings:
            notif = self._notify(user_id, p)
            if notif is not None:
                created.append(notif)
        self.db.flush()
        return created

    # ── gather every transaction as a signed-cents MatchRow ──────────────

    def _all_match_rows(self, user_id: int) -> list[MatchRow]:
        """All of the user's transactions across all accounts, signed.

        Tagged with a ``("expense"|"income", id)`` ref so the notification ref is
        stable and order-independent regardless of which side of the pair a row
        sits on.
        """
        account_ids = self.db.execute(
            select(AccountORM.id).where(AccountORM.user_id == user_id)
        ).scalars().all()
        if not account_ids:
            return []

        rows: list[MatchRow] = []
        expenses = self.db.execute(
            select(ExpenseORM).where(ExpenseORM.account_id.in_(account_ids))
        ).scalars()
        for e in expenses:
            rows.append(
                MatchRow(
                    ref=("expense", e.id),
                    title=e.title,
                    amount_cents=-abs(e.amount),  # money out
                    date=e.date,
                    account_id=e.account_id,
                )
            )
        incomes = self.db.execute(
            select(IncomeORM).where(IncomeORM.account_id.in_(account_ids))
        ).scalars()
        for i in incomes:
            rows.append(
                MatchRow(
                    ref=("income", i.id),
                    title=i.title,
                    amount_cents=abs(i.amount),  # money in
                    date=i.date,
                    account_id=i.account_id,
                )
            )
        return rows

    # ── surface a pairing as a deduplicated notification ─────────────────

    def _notify(self, user_id: int, p: Pairing) -> Optional[NotificationORM]:
        ref = self._ref_for(p)
        exists = self.db.execute(
            select(NotificationORM.id).where(
                NotificationORM.user_id == user_id,
                NotificationORM.ref == ref,
            )
        ).first()
        if exists:
            return None

        title, template = _KIND_COPY[p.kind]
        message = template.format(
            a=p.a.title,
            b=p.b.title,
            amount=cents_to_dollars(p.a.magnitude),
        )
        notif = NotificationORM(
            user_id=user_id,
            type="detangle",
            title=title,
            message=message,
            ref=ref,
        )
        self.db.add(notif)
        return notif

    @staticmethod
    def _ref_for(p: Pairing) -> str:
        """A stable, order-independent dedup key for a pairing.

        Sorting the two refs means a pair is the same ref no matter which row the
        matcher named ``a`` vs ``b``, so a re-run can't create a mirror-image
        duplicate notification.
        """
        keys = sorted(f"{kind}:{rid}" for kind, rid in (p.a.ref, p.b.ref))
        return f"detangle:{p.kind}:{keys[0]}:{keys[1]}"
