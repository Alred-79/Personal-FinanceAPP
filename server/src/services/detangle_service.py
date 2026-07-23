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

from typing import Optional, Sequence

from sqlalchemy import func, select
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
        "A ${amount:.2f} debit and credit — “{a}” and “{b}” — posted {gap} "
        "across different accounts. A description or category includes a transfer "
        "marker. Review the pair.",
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
        """The user's recent transactions across all accounts, signed.

        L4: bounded to a recent lookback window (``detangle_scan_window_days``)
        rather than the ENTIRE history — a transfer/refund/duplicate is always
        recent (it must be within ``window_days`` of its partner), so windowing the
        fetch keeps the O(n²) pairing near-linear without changing what's found for
        recent data. Tagged with a ``("expense"|"income", id)`` ref so the
        notification ref is stable regardless of which side of the pair a row sits.
        """
        account_ids = self.db.execute(
            select(AccountORM.id).where(AccountORM.user_id == user_id)
        ).scalars().all()
        if not account_ids:
            return []

        cutoff = self._scan_cutoff(account_ids)

        def _expense_q():
            q = select(ExpenseORM).where(ExpenseORM.account_id.in_(account_ids))
            return q.where(ExpenseORM.date >= cutoff) if cutoff else q

        def _income_q():
            q = select(IncomeORM).where(IncomeORM.account_id.in_(account_ids))
            return q.where(IncomeORM.date >= cutoff) if cutoff else q

        rows: list[MatchRow] = []
        for e in self.db.execute(_expense_q()).scalars():
            rows.append(
                MatchRow(
                    ref=("expense", e.id),
                    title=e.title,
                    amount_cents=-abs(e.amount),  # money out
                    date=e.date,
                    account_id=e.account_id,
                    category=e.category or "",
                )
            )
        for i in self.db.execute(_income_q()).scalars():
            rows.append(
                MatchRow(
                    ref=("income", i.id),
                    title=i.title,
                    amount_cents=abs(i.amount),  # money in
                    date=i.date,
                    account_id=i.account_id,
                    category=i.category or "",
                )
            )
        return rows

    def _scan_cutoff(self, account_ids: Sequence[int]) -> Optional[str]:
        """ISO date string N days before the user's LATEST transaction, or None
        when windowing is disabled.

        Windowing relative to the most recent transaction (not wall-clock today)
        makes detection deterministic regardless of when the nightly job runs vs.
        when data last synced, and still bounds the scan in production (recent
        syncs → latest ≈ now → a recent window). ``date`` columns are ISO
        ``YYYY-MM-DD`` strings, which sort chronologically, so MAX() and a string
        ``>= cutoff`` are both correct without a cast.
        """
        from datetime import date, timedelta

        from ..settings import settings

        days = getattr(settings, "detangle_scan_window_days", 0)
        if not days or days <= 0:
            return None
        latest = self.db.execute(
            select(func.max(ExpenseORM.date)).where(
                ExpenseORM.account_id.in_(account_ids)
            )
        ).scalar()
        latest_inc = self.db.execute(
            select(func.max(IncomeORM.date)).where(
                IncomeORM.account_id.in_(account_ids)
            )
        ).scalar()
        anchor_str = max(s for s in (latest, latest_inc) if s) if (latest or latest_inc) else None
        if not anchor_str:
            return None
        try:
            anchor = date.fromisoformat(str(anchor_str)[:10])
        except ValueError:
            return None
        return (anchor - timedelta(days=int(days))).isoformat()

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
            gap=self._date_gap(p),
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
    def _date_gap(p: Pairing) -> str:
        from datetime import date

        try:
            a = p.a.date if isinstance(p.a.date, date) else date.fromisoformat(str(p.a.date))
            b = p.b.date if isinstance(p.b.date, date) else date.fromisoformat(str(p.b.date))
            days = abs((a - b).days)
        except (TypeError, ValueError):
            return "within the review window"
        return "the same day" if days == 0 else f"{days} day{'s' if days != 1 else ''} apart"

    @staticmethod
    def _ref_for(p: Pairing) -> str:
        """A stable, order-independent dedup key for a pairing.

        Sorting the two refs means a pair is the same ref no matter which row the
        matcher named ``a`` vs ``b``, so a re-run can't create a mirror-image
        duplicate notification.
        """
        keys = sorted(f"{kind}:{rid}" for kind, rid in (p.a.ref, p.b.ref))
        return f"detangle:{p.kind}:{keys[0]}:{keys[1]}"
