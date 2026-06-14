"""Pillar 3 — the quarterly estimated-tax reminder job.

Donor pattern: ``job_check_plan_drift`` / ``job_detangle``. The job must be
idempotent per ``ref``, self-gate on ``tax_features_enabled``, and emit a
FACTUAL, NON-DIRECTIVE message (no "you should pay").
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Notification as NotificationORM,
    User as UserORM,
)
from server.src.scheduler import job_tax_quarterly_reminder
from server.src.services.tax.tagging_service import TaxTaggingService


def _user(db, username="alice"):
    u = UserORM(username=username, full_name="A", email=f"{username}@e.com",
                hashed_password="x")
    db.add(u)
    db.flush()
    return u


def _enable_tax(monkeypatch):
    from server.src.settings import settings
    monkeypatch.setattr(settings, "tax_features_enabled", True, raising=False)


# A date 10 days before the Q2 2026 due date (Jun 16) — inside the 14-day window.
_NEAR_Q2 = datetime(2026, 6, 6)


class TestQuarterlyReminderJob:
    def test_self_gates_when_disabled(self, db_session, monkeypatch):
        from server.src.settings import settings
        monkeypatch.setattr(settings, "tax_features_enabled", False, raising=False)
        _user(db_session)
        assert job_tax_quarterly_reminder(db_session, _NEAR_Q2) == 0

    def test_fires_within_window(self, db_session, monkeypatch):
        _enable_tax(monkeypatch)
        u = _user(db_session)
        a = AccountORM(name="Checking", type="depository", balance=0, user_id=u.id)
        db_session.add(a)
        db_session.flush()
        e = ExpenseORM(title="Staples", amount=6000, date="2026-03-01",
                       category="Shops", account_id=a.id)
        db_session.add(e)
        db_session.flush()
        TaxTaggingService(db_session).tag(
            u.id, tx_type="expense", tx_id=e.id, tax_year=2026,
            bucket="sch_c_18_office",
        )
        created = job_tax_quarterly_reminder(db_session, _NEAR_Q2)
        assert created == 1
        notif = db_session.execute(
            select(NotificationORM).where(
                NotificationORM.type == "tax_estimate_reminder"
            )
        ).scalar_one()
        # Factual + non-directive: states the date and the user's own numbers,
        # never "you should pay".
        assert "approaching" in notif.message
        assert "you should" not in notif.message.lower()
        assert "organization only" in notif.message.lower()

    def test_idempotent_per_ref(self, db_session, monkeypatch):
        _enable_tax(monkeypatch)
        _user(db_session)
        first = job_tax_quarterly_reminder(db_session, _NEAR_Q2)
        second = job_tax_quarterly_reminder(db_session, _NEAR_Q2)
        assert first == 1
        assert second == 0  # the ref dedup prevents a duplicate
        rows = db_session.execute(
            select(NotificationORM).where(
                NotificationORM.type == "tax_estimate_reminder"
            )
        ).scalars().all()
        assert len(rows) == 1

    def test_no_fire_far_from_due_date(self, db_session, monkeypatch):
        _enable_tax(monkeypatch)
        _user(db_session)
        # Feb 1 — far from any due date.
        assert job_tax_quarterly_reminder(db_session, datetime(2026, 2, 1)) == 0
