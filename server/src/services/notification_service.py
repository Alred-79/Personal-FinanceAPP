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
        base = (
            select(ExpenseORM)
            .join(AccountORM, ExpenseORM.account_id == AccountORM.id)
            .where(AccountORM.user_id == user_id)
        )
        # L4: bound the scan to a recent window instead of the user's ENTIRE
        # history. The window is anchored on the user's LATEST expense (not
        # wall-clock today) so detection is deterministic regardless of when the
        # nightly job runs vs. when data synced, and still bounds the scan in
        # production. ``Expense.date`` is an ISO string (sorts chronologically), so
        # MAX() and a string ``>= cutoff`` are both correct without a cast.
        cutoff = self._anomaly_cutoff(user_id, today)
        stmt = base.where(ExpenseORM.date >= cutoff) if cutoff else base
        rows = self.db.execute(stmt).scalars().all()

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

    # ── Retention (L4) ───────────────────────────────────────────────────

    def prune(
        self,
        user_id: int,
        *,
        today: Optional[date] = None,
        retention_days: int,
        max_per_user: int,
    ) -> int:
        """Delete OLD, READ notifications for one user; cap total rows.

        Never deletes an unread/actionable notice — only ``read == 1`` rows whose
        ``created_at`` is older than ``retention_days``. After the age sweep, if the
        user still has more than ``max_per_user`` rows, the oldest READ rows beyond
        the cap are removed too (unread rows are always kept). Idempotent: a second
        run with nothing stale deletes nothing. Returns the number deleted.
        """
        from datetime import datetime, time, timedelta

        today = today or date.today()
        deleted = 0

        # 1) Age sweep — read rows older than the cutoff. created_at is a timestamp;
        # compare against the start of the cutoff day.
        if retention_days and retention_days > 0:
            cutoff_dt = datetime.combine(
                today - timedelta(days=int(retention_days)), time.min
            )
            stale = (
                self.db.execute(
                    select(NotificationORM).where(
                        NotificationORM.user_id == user_id,
                        NotificationORM.read == 1,
                        NotificationORM.created_at < cutoff_dt,
                    )
                )
                .scalars()
                .all()
            )
            for row in stale:
                self.db.delete(row)
                deleted += 1

        # 2) Cap — if still over max_per_user, drop the oldest READ rows beyond the
        # cap. Unread rows are never counted out / deleted (always actionable).
        if max_per_user and max_per_user > 0:
            total = int(
                self.db.execute(
                    select(func.count(NotificationORM.id)).where(
                        NotificationORM.user_id == user_id
                    )
                ).scalar()
                or 0
            )
            # account for rows deleted above (not yet flushed/counted)
            total -= deleted
            overflow = total - int(max_per_user)
            if overflow > 0:
                oldest_read = (
                    self.db.execute(
                        select(NotificationORM)
                        .where(
                            NotificationORM.user_id == user_id,
                            NotificationORM.read == 1,
                        )
                        .order_by(
                            NotificationORM.created_at.asc(),
                            NotificationORM.id.asc(),
                        )
                        .limit(overflow)
                    )
                    .scalars()
                    .all()
                )
                for row in oldest_read:
                    self.db.delete(row)
                    deleted += 1

        if deleted:
            self.db.flush()
        return deleted

    def _anomaly_cutoff(self, user_id: int, today: date) -> Optional[str]:
        """ISO cutoff N days before the user's LATEST expense, or None when the
        window is disabled (``anomaly_scan_window_days <= 0``)."""
        from datetime import timedelta

        from server.src.settings import settings

        window = getattr(settings, "anomaly_scan_window_days", 0)
        if not window or window <= 0:
            return None
        latest = self.db.execute(
            select(func.max(ExpenseORM.date))
            .join(AccountORM, ExpenseORM.account_id == AccountORM.id)
            .where(AccountORM.user_id == user_id)
        ).scalar()
        if not latest:
            return None
        try:
            anchor = date.fromisoformat(str(latest)[:10])
        except ValueError:
            anchor = today
        return (anchor - timedelta(days=int(window))).isoformat()

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
