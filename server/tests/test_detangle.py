"""The Detangler — flag transfer/refund/duplicate pairs across all transactions.

Service-level (truth of detection + notification dedup) and the on-demand
endpoint. Reuses the matching engine; no Groq, no network.
"""

from sqlalchemy import select

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
    Notification as NotificationORM,
    User as UserORM,
)
from server.src.scheduler import job_detangle
from server.src.services.detangle_service import DetangleService


def _user(db, username="alice"):
    u = UserORM(
        username=username, full_name="A", email=f"{username}@e.com", hashed_password="x"
    )
    db.add(u)
    db.flush()
    return u


def _account(db, user_id, name="Checking"):
    a = AccountORM(name=name, type="depository", balance=0, user_id=user_id)
    db.add(a)
    db.flush()
    return a


def _expense(db, account_id, title, dollars, date):
    db.add(
        ExpenseORM(
            title=title, amount=int(round(dollars * 100)), date=date,
            category="Other", account_id=account_id,
        )
    )
    db.flush()


def _income(db, account_id, title, dollars, date):
    db.add(
        IncomeORM(
            title=title, amount=int(round(dollars * 100)), date=date,
            category="Work", account_id=account_id,
        )
    )
    db.flush()


def _notes(db, user_id):
    return db.execute(
        select(NotificationORM).where(NotificationORM.user_id == user_id)
    ).scalars().all()


# ── detection ────────────────────────────────────────────────────────────────

def test_flags_transfer_between_accounts(db_session):
    u = _user(db_session)
    checking = _account(db_session, u.id, "Checking")
    savings = _account(db_session, u.id, "Savings")
    _expense(db_session, checking.id, "Transfer to Savings", 500.0, "2026-03-01")
    _income(db_session, savings.id, "Transfer from Checking", 500.0, "2026-03-02")

    created = DetangleService(db_session).run(u.id)
    assert len(created) == 1
    assert created[0].type == "detangle"
    assert "transfer" in created[0].title.lower()


def test_flags_refund_same_merchant(db_session):
    u = _user(db_session)
    a = _account(db_session, u.id)
    _expense(db_session, a.id, "Amazon", 40.0, "2026-03-01")
    _income(db_session, a.id, "Amazon", 40.0, "2026-03-03")

    created = DetangleService(db_session).run(u.id)
    assert len(created) == 1
    assert "refund" in created[0].title.lower()


def test_flags_duplicate_same_account(db_session):
    u = _user(db_session)
    a = _account(db_session, u.id)
    _expense(db_session, a.id, "Starbucks #1", 6.50, "2026-03-01")
    _expense(db_session, a.id, "Starbucks #2", 6.50, "2026-03-01")  # same key, amount, day

    created = DetangleService(db_session).run(u.id)
    assert len(created) == 1
    assert "duplicate" in created[0].title.lower()


def test_unrelated_transactions_flag_nothing(db_session):
    u = _user(db_session)
    a = _account(db_session, u.id)
    _expense(db_session, a.id, "Rent", 1200.0, "2026-03-01")
    _income(db_session, a.id, "Salary", 3000.0, "2026-03-02")
    assert DetangleService(db_session).run(u.id) == []


def test_run_is_idempotent(db_session):
    u = _user(db_session)
    checking = _account(db_session, u.id, "Checking")
    savings = _account(db_session, u.id, "Savings")
    _expense(db_session, checking.id, "Transfer", 500.0, "2026-03-01")
    _income(db_session, savings.id, "Transfer", 500.0, "2026-03-01")

    first = DetangleService(db_session).run(u.id)
    second = DetangleService(db_session).run(u.id)
    assert len(first) == 1
    assert second == []  # dedup on ref → no new notification
    assert len(_notes(db_session, u.id)) == 1


def test_scoped_per_user(db_session):
    alice = _user(db_session, "alice")
    bob = _user(db_session, "bob")
    a_chk = _account(db_session, alice.id, "Checking")
    a_sav = _account(db_session, alice.id, "Savings")
    _expense(db_session, a_chk.id, "Transfer", 500.0, "2026-03-01")
    _income(db_session, a_sav.id, "Transfer", 500.0, "2026-03-01")
    # Bob has a similar-looking pair; running for Alice must not touch Bob.
    b = _account(db_session, bob.id)
    _expense(db_session, b.id, "Transfer", 500.0, "2026-03-01")

    DetangleService(db_session).run(alice.id)
    assert len(_notes(db_session, alice.id)) == 1
    assert len(_notes(db_session, bob.id)) == 0


def test_job_detangle_runs_all_users(db_session):
    alice = _user(db_session, "alice")
    chk = _account(db_session, alice.id, "Checking")
    sav = _account(db_session, alice.id, "Savings")
    _expense(db_session, chk.id, "Transfer", 250.0, "2026-03-01")
    _income(db_session, sav.id, "Transfer", 250.0, "2026-03-01")
    total = job_detangle(db_session)
    assert total == 1
