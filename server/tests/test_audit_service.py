"""F3 — Nightly Auditor tests.

A run_due-style test (à la test_game_scheduler) with the scheduler never started:
plant findings, run the job directly, and assert exactly one notification per
finding, stable ref dedup on re-run, the batch capped, and the narration screened
by the firewall. Idempotent and deterministic.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from server.src import scheduler
from server.src.db.models import (
    Account as AccountORM,
    Budget as BudgetORM,
    Expense as ExpenseORM,
    Notification as NotificationORM,
    User as UserORM,
)
from server.src.services.audit_service import AuditService
from server.src.services.game.firewall import REDIRECT_IN_CHARACTER
from server.src.settings import settings

AS_OF = date(2026, 6, 15)


def _seed_user(db):
    user = UserORM(username="aud", full_name="Aud U", email="aud@x.com",
                   hashed_password="x", savings_percent=0)
    db.add(user)
    db.flush()
    acct = AccountORM(name="Checking", type="checking", balance=5_000_00,
                      user_id=user.id)
    db.add(acct)
    db.flush()
    return user, acct


def _charges_back(db, acct_id, title, n, step_days, end_offset, amount_cents):
    """``n`` charges spaced ``step_days`` apart, the most recent ``end_offset``
    days before AS_OF."""
    for k in range(n):
        d = AS_OF - timedelta(days=end_offset + step_days * k)
        db.add(ExpenseORM(title=title, amount=amount_cents, date=d.isoformat(),
                          category="Subscriptions", account_id=acct_id))


def _count(db, user_id, type_):
    return db.query(NotificationORM).filter(
        NotificationORM.user_id == user_id, NotificationORM.type == type_
    ).count()


@pytest.fixture
def planted(db_session, monkeypatch):
    monkeypatch.setattr(settings, "auditor_enabled", True)
    monkeypatch.setattr(settings, "merchant_lifecycle_enabled", True)
    user, acct = _seed_user(db_session)

    # An anomalous charge: a category of small charges plus one giant one.
    for d in ("2026-05-02", "2026-05-09", "2026-05-16", "2026-05-23"):
        db_session.add(ExpenseORM(title="Coffee", amount=10_00, date=d,
                                  category="Food", account_id=acct.id))
    db_session.add(ExpenseORM(title="Catering blowout", amount=500_00,
                              date="2026-05-30", category="Food", account_id=acct.id))

    # A budget overrun this month (Dining capped at $10, spent $80).
    db_session.add(BudgetORM(user_id=user.id, category="Dining",
                             monthly_limit=10_00, rollover=0))
    db_session.add(ExpenseORM(title="Dinner", amount=80_00, date="2026-06-03",
                              category="Dining", account_id=acct.id))

    # Lifecycle population: 6 healthy monthly subs (charging up to AS_OF) +
    # 1 planted zombie (silent ~6 months).
    for name in ("Spotify", "Netflix", "Hulu", "Cloudbox", "Newsdesk", "Audible"):
        _charges_back(db_session, acct.id, name, 13, 30, 0, 15_00)
    _charges_back(db_session, acct.id, "Deadsub", 7, 30, 180, 40_00)
    db_session.flush()
    return user


def test_auditor_composes_findings_and_dedups(db_session, planted):
    first = scheduler.job_auditor(db_session, AS_OF)
    db_session.flush()
    assert first > 0
    assert _count(db_session, planted.id, "anomaly") == 1
    assert _count(db_session, planted.id, "budget_overrun") == 1
    assert _count(db_session, planted.id, "merchant_lifecycle") >= 1  # the zombie
    assert _count(db_session, planted.id, "audit_digest") == 1

    # Re-run is a no-op: every finding deduped by ref, no second digest.
    second = scheduler.job_auditor(db_session, AS_OF)
    db_session.flush()
    assert second == 0
    assert _count(db_session, planted.id, "audit_digest") == 1
    assert _count(db_session, planted.id, "merchant_lifecycle") >= 1


def test_auditor_caps_batch(db_session, monkeypatch):
    """More zombie findings than the cap → only the cap is surfaced (alert
    fatigue guard), never a silent flood."""
    monkeypatch.setattr(settings, "auditor_enabled", True)
    monkeypatch.setattr(settings, "merchant_lifecycle_enabled", True)
    monkeypatch.setattr(settings, "auditor_max_findings", 3)
    user, acct = _seed_user(db_session)
    # 6 healthy (for a fittable population) + 6 zombies → 6 dormant findings > cap.
    for name in ("Spotify", "Netflix", "Hulu", "Cloudbox", "Newsdesk", "Audible"):
        _charges_back(db_session, acct.id, name, 13, 30, 0, 15_00)
    for name in ("Deadone", "Deadtwo", "Deadthree", "Deadfour", "Deadfive", "Deadsix"):
        _charges_back(db_session, acct.id, name, 7, 30, 180, 40_00)
    db_session.flush()

    scheduler.job_auditor(db_session, AS_OF)
    db_session.flush()
    assert _count(db_session, user.id, "merchant_lifecycle") == 3  # capped


def test_auditor_narration_screened_by_firewall(db_session, planted):
    """A model that ignores its prompt and gives advice is blocked: the digest
    carries the firewall redirect, never the advice."""
    def rogue_llm(_prompt: str) -> str:
        return "You should invest in stocks and move your savings into crypto."

    AuditService(db_session).run(planted.id, as_of=AS_OF, llm_call=rogue_llm)
    db_session.flush()
    digest = db_session.query(NotificationORM).filter(
        NotificationORM.user_id == planted.id,
        NotificationORM.type == "audit_digest",
    ).one()
    assert digest.message == REDIRECT_IN_CHARACTER
    assert "invest" not in digest.message


def test_auditor_disabled_is_noop(db_session, planted, monkeypatch):
    monkeypatch.setattr(settings, "auditor_enabled", False)
    assert scheduler.job_auditor(db_session, AS_OF) == 0
    assert _count(db_session, planted.id, "audit_digest") == 0
