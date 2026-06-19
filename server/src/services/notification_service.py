"""Notification and nudge service.

Builds two kinds of nudges and saves them as ``Notification`` rows:

* **budget_overrun**: a category's spend so far this month is past its budget
  (it reuses the ``BudgetService`` summary).
* **anomaly**: a single expense is way bigger than that category's usual charge
  (``is_anomalous`` is a pure helper with its own unit tests).

Generation is idempotent: each notification carries a stable ``ref`` dedup key,
so running ``generate`` again while a nudge is still unread won't make a
duplicate.
"""

from __future__ import annotations

import statistics
from datetime import date
from typing import Any, Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Notification as NotificationORM,
)
from server.src.money import cents_to_dollars
from server.src.services.budget_service import BudgetService

# Anomaly thresholds.
_ANOMALY_MIN_HISTORY = 4  # need enough history to have a "normal"
_ANOMALY_MULTIPLE = 3.0  # charge must exceed this multiple of the median
_ANOMALY_SIGMA = 3.0  # …or this many standard deviations above the mean


def is_anomalous(amount: float, history: list[float]) -> bool:
    """True if *amount* is an outlier next to *history* (which excludes *amount*).

    Needs at least ``_ANOMALY_MIN_HISTORY`` earlier values. It flags a charge
    that is both well above the median (a sturdy center) and beyond a few
    standard deviations of the mean, so a category full of large charges
    doesn't fire over and over.

    >>> is_anomalous(500, [10, 12, 11, 9, 10])
    True
    >>> is_anomalous(13, [10, 12, 11, 9, 10])
    False
    """
    if len(history) < _ANOMALY_MIN_HISTORY:
        return False
    median = statistics.median(history)
    if median <= 0:
        return False
    if amount <= _ANOMALY_MULTIPLE * median:
        return False
    mean = statistics.fmean(history)
    stdev = statistics.pstdev(history)
    if stdev == 0:
        return True  # perfectly uniform history, and amount > 3x median
    return amount > mean + _ANOMALY_SIGMA * stdev


class NotificationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Generation ───────────────────────────────────────────────────────

    def generate(
        self, user_id: int, today: Optional[date] = None
    ) -> list[NotificationORM]:
        """Create the budget overrun and anomaly notifications, returning the new rows."""
        today = today or date.today()
        created: list[NotificationORM] = []
        created.extend(self._generate_budget_overruns(user_id, today))
        created.extend(self._generate_anomalies(user_id, today))
        if created:
            self.db.flush()
        return created

    def _add_if_new(
        self, user_id: int, *, type: str, title: str, message: str, ref: str
    ) -> Optional[NotificationORM]:
        """Insert a notification unless one with the same ref already exists.

        Read or unread: a nudge the user has already seen and dismissed must
        not resurrect on the next feed refresh (the ref embeds the period or
        item id, so a *new* overrun next month still gets its own row).
        """
        exists = self.db.execute(
            select(NotificationORM.id).where(
                NotificationORM.user_id == user_id,
                NotificationORM.ref == ref,
            )
        ).first()
        if exists:
            return None
        notif = NotificationORM(
            user_id=user_id, type=type, title=title, message=message, ref=ref
        )
        self.db.add(notif)
        return notif

    def _generate_budget_overruns(
        self, user_id: int, today: date
    ) -> list[NotificationORM]:
        created: list[NotificationORM] = []
        period = today.strftime("%Y-%m")
        for summary in BudgetService(self.db).summarize(user_id, today):
            if not summary["over_budget"]:
                continue
            category = summary["category"]
            ref = f"budget_overrun:{category}:{period}"
            notif = self._add_if_new(
                user_id,
                type="budget_overrun",
                title=f"Over budget: {category}",
                message=(
                    f"You've spent ${summary['spent']:,.2f} of your "
                    f"${summary['effective_limit']:,.2f} {category} budget "
                    f"this month."
                ),
                ref=ref,
            )
            if notif is not None:
                created.append(notif)
        return created

    def _generate_anomalies(
        self, user_id: int, today: date
    ) -> list[NotificationORM]:
        created: list[NotificationORM] = []
        rows = (
            self.db.execute(
                select(ExpenseORM)
                .join(AccountORM, ExpenseORM.account_id == AccountORM.id)
                .where(AccountORM.user_id == user_id)
            )
            .scalars()
            .all()
        )

        by_category: dict[str, list[Any]] = {}
        for r in rows:
            by_category.setdefault(r.category, []).append(r)

        for category, items in by_category.items():
            for item in items:
                amount = cents_to_dollars(item.amount)
                history = [
                    cents_to_dollars(o.amount) for o in items if o.id != item.id
                ]
                if not is_anomalous(amount, history):
                    continue
                ref = f"anomaly:{item.id}"
                notif = self._add_if_new(
                    user_id,
                    type="anomaly",
                    title=f"Unusual charge: {category}",
                    message=(
                        f"{item.title} for ${amount:,.2f} is much larger than "
                        f"your typical {category} spending."
                    ),
                    ref=ref,
                )
                if notif is not None:
                    created.append(notif)
        return created

    # ── Read API ─────────────────────────────────────────────────────────

    def list(
        self, user_id: int, unread_only: bool = False, limit: int = 50
    ) -> list[dict[str, Any]]:
        stmt = select(NotificationORM).where(NotificationORM.user_id == user_id)
        if unread_only:
            stmt = stmt.where(NotificationORM.read == 0)
        stmt = stmt.order_by(NotificationORM.created_at.desc(), NotificationORM.id.desc()).limit(limit)
        rows = self.db.execute(stmt).scalars().all()
        return [self._to_dict(r) for r in rows]

    def unread_count(self, user_id: int) -> int:
        return int(
            self.db.execute(
                select(func.count(NotificationORM.id)).where(
                    NotificationORM.user_id == user_id,
                    NotificationORM.read == 0,
                )
            ).scalar()
            or 0
        )

    def mark_read(self, user_id: int, notification_id: int) -> bool:
        notif = self.db.execute(
            select(NotificationORM).where(
                NotificationORM.id == notification_id,
                NotificationORM.user_id == user_id,
            )
        ).scalar_one_or_none()
        if notif is None:
            return False
        notif.read = 1
        self.db.flush()
        return True

    def mark_all_read(self, user_id: int) -> int:
        rows = (
            self.db.execute(
                select(NotificationORM).where(
                    NotificationORM.user_id == user_id,
                    NotificationORM.read == 0,
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            r.read = 1
        self.db.flush()
        return len(rows)

    @staticmethod
    def _to_dict(r: NotificationORM) -> dict[str, Any]:
        return {
            "id": r.id,
            "type": r.type,
            "title": r.title,
            "message": r.message,
            "read": bool(r.read),
            "created_at": str(r.created_at) if r.created_at else None,
        }
