"""Net worth snapshot service.

Net worth is the sum of all of a user's account balances.  We persist a daily
``BalanceSnapshot`` so the Overview chart can plot a trend over time.

Snapshotting is idempotent per day: ``record_snapshot`` upserts the row for the
given date, so calling it repeatedly within a day just refreshes today's total
(a lightweight "lazy daily snapshot" hook driven by reads).
"""

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import BalanceSnapshot as BalanceSnapshotORM
from server.src.money import cents_to_dollars
from server.src.services.account_semantics import AccountSemanticsService


class NetWorthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def current_total_cents(self, user_id: int) -> int:
        """Purpose-aware assets minus liabilities for *user_id*."""
        return AccountSemanticsService(self.db).total_cents(user_id, "net_worth")

    def record_snapshot(
        self, user_id: int, on_date: date | None = None
    ) -> BalanceSnapshotORM:
        """Upsert the snapshot for *on_date* (defaults to today)."""
        on_date = on_date or date.today()
        day = on_date.isoformat()

        snapshot = self.db.execute(
            select(BalanceSnapshotORM).where(
                BalanceSnapshotORM.user_id == user_id,
                BalanceSnapshotORM.date == day,
            )
        ).scalar_one_or_none()

        total = self.current_total_cents(user_id)
        if snapshot is None:
            snapshot = BalanceSnapshotORM(
                user_id=user_id, date=day, total=total
            )
            self.db.add(snapshot)
        else:
            snapshot.total = total  # type: ignore[assignment]
        self.db.flush()
        return snapshot

    def get_series(self, user_id: int) -> list[dict[str, Any]]:
        """Ensure today's snapshot exists, then return the full trend series."""
        self.record_snapshot(user_id)
        rows = (
            self.db.execute(
                select(BalanceSnapshotORM)
                .where(BalanceSnapshotORM.user_id == user_id)
                .order_by(BalanceSnapshotORM.date.asc())
            )
            .scalars()
            .all()
        )
        return [
            {"date": r.date, "total": cents_to_dollars(r.total)}  # type: ignore[arg-type]
            for r in rows
        ]
