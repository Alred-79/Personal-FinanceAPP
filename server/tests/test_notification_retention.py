"""L4 — notification retention sweep + scan windowing.

Retention: delete only OLD READ rows, cap per user, never touch unread.
Windowing: detangle/anomaly scans bound to a recent window (anchored on the
latest transaction) without changing detection for recent data.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
    Notification as NotificationORM,
    User as UserORM,
)
from server.src.scheduler import job_notification_retention
from server.src.services.detangle_service import DetangleService
from server.src.services.notification_service import NotificationService
from server.src.settings import settings


def _user(db, username="ret"):
    u = UserORM(
        username=username, full_name="R", email=f"{username}@e.com", hashed_password="x"
    )
    db.add(u)
    db.flush()
    return u


def _account(db, user_id, name="Checking"):
    a = AccountORM(name=name, type="depository", balance=0, user_id=user_id)
    db.add(a)
    db.flush()
    return a


def _notif(db, user_id, *, read, created_at, ref):
    n = NotificationORM(
        user_id=user_id, type="anomaly", title="t", message="m",
        ref=ref, read=read, created_at=created_at,
    )
    db.add(n)
    db.flush()
    return n


def _count(db, user_id):
    return len(
        db.execute(
            select(NotificationORM).where(NotificationORM.user_id == user_id)
        ).scalars().all()
    )


# ── retention ──────────────────────────────────────────────────────────────

def test_prune_deletes_old_read_keeps_unread_and_recent(db_session):
    u = _user(db_session)
    now = datetime(2026, 6, 19, 12, 0, 0)
    old = now - timedelta(days=200)
    recent = now - timedelta(days=5)

    old_read = _notif(db_session, u.id, read=1, created_at=old, ref="old_read")
    old_unread = _notif(db_session, u.id, read=0, created_at=old, ref="old_unread")
    recent_read = _notif(db_session, u.id, read=1, created_at=recent, ref="recent_read")

    deleted = NotificationService(db_session).prune(
        u.id, today=now.date(), retention_days=90, max_per_user=500
    )
    assert deleted == 1
    remaining = {
        n.ref for n in db_session.execute(
            select(NotificationORM).where(NotificationORM.user_id == u.id)
        ).scalars()
    }
    # Only the OLD READ row is gone; unread (even old) and recent are kept.
    assert remaining == {"old_unread", "recent_read"}
    assert db_session.get(NotificationORM, old_read.id) is None


def test_prune_caps_per_user_dropping_oldest_read_only(db_session):
    u = _user(db_session)
    now = datetime(2026, 6, 19, 12, 0, 0)
    # 5 recent READ rows + 2 unread. Cap at 3 → drop the 4 oldest READ beyond cap,
    # but unread are never dropped, so 2 unread + (cap - 2 unread is not how it
    # works) — cap counts ALL rows: total 7, cap 3 → overflow 4, drop 4 oldest READ.
    reads = [
        _notif(db_session, u.id, read=1,
               created_at=now - timedelta(days=i), ref=f"r{i}")
        for i in range(5)
    ]
    unreads = [
        _notif(db_session, u.id, read=0,
               created_at=now - timedelta(days=100 + i), ref=f"u{i}")
        for i in range(2)
    ]
    deleted = NotificationService(db_session).prune(
        u.id, today=now.date(), retention_days=0, max_per_user=3
    )
    assert deleted == 4  # 7 total - cap 3
    survivors = {
        n.ref for n in db_session.execute(
            select(NotificationORM).where(NotificationORM.user_id == u.id)
        ).scalars()
    }
    # Both unread always survive; only the newest READ survives (oldest READ dropped).
    assert {"u0", "u1"}.issubset(survivors)
    assert "r0" in survivors  # newest read kept
    assert "r4" not in survivors  # oldest read dropped


def test_prune_is_idempotent(db_session):
    u = _user(db_session)
    now = datetime(2026, 6, 19, 12, 0, 0)
    _notif(db_session, u.id, read=1, created_at=now - timedelta(days=5), ref="keep")
    svc = NotificationService(db_session)
    assert svc.prune(u.id, today=now.date(), retention_days=90, max_per_user=500) == 0
    assert svc.prune(u.id, today=now.date(), retention_days=90, max_per_user=500) == 0
    assert _count(db_session, u.id) == 1


def test_job_notification_retention_runs_all_users(db_session, monkeypatch):
    monkeypatch.setattr(settings, "notification_retention_enabled", True)
    monkeypatch.setattr(settings, "notification_retention_days", 90)
    monkeypatch.setattr(settings, "notification_retention_max_per_user", 500)
    now = datetime(2026, 6, 19, 12, 0, 0)
    a = _user(db_session, "ra")
    b = _user(db_session, "rb")
    _notif(db_session, a.id, read=1, created_at=now - timedelta(days=200), ref="a_old")
    _notif(db_session, b.id, read=1, created_at=now - timedelta(days=200), ref="b_old")
    _notif(db_session, b.id, read=0, created_at=now - timedelta(days=200), ref="b_unread")

    deleted = job_notification_retention(db_session, now)
    assert deleted == 2  # one old-read per user
    assert _count(db_session, a.id) == 0
    assert _count(db_session, b.id) == 1  # the unread survives


def test_retention_disabled_is_noop(db_session, monkeypatch):
    monkeypatch.setattr(settings, "notification_retention_enabled", False)
    now = datetime(2026, 6, 19, 12, 0, 0)
    u = _user(db_session, "rc")
    _notif(db_session, u.id, read=1, created_at=now - timedelta(days=999), ref="old")
    assert job_notification_retention(db_session, now) == 0
    assert _count(db_session, u.id) == 1


# ── scan windowing ───────────────────────────────────────────────────────────

def test_detangle_window_identical_on_recent_data(db_session, monkeypatch):
    """The windowed scan finds the same pair as an unwindowed scan when the data
    is recent (the L4 no-silent-behavior-change guard)."""
    u = _user(db_session)
    chk = _account(db_session, u.id, "Checking")
    sav = _account(db_session, u.id, "Savings")
    # Recent transfer pair (both within any sane window of each other).
    db_session.add_all([
        ExpenseORM(title="Xfer", amount=50000, date="2026-06-10",
                   category="Other", account_id=chk.id),
        IncomeORM(title="Xfer", amount=50000, date="2026-06-11",
                  category="Work", account_id=sav.id),
    ])
    db_session.flush()

    # Windowed (default 90d).
    created_windowed = DetangleService(db_session).run(u.id)
    assert len(created_windowed) == 1

    # Clear notifications, disable the window, re-run → same single pair.
    for n in db_session.execute(
        select(NotificationORM).where(NotificationORM.user_id == u.id)
    ).scalars().all():
        db_session.delete(n)
    db_session.flush()
    monkeypatch.setattr(settings, "detangle_scan_window_days", 0)
    created_full = DetangleService(db_session).run(u.id)
    assert len(created_full) == 1
    assert created_full[0].ref == created_windowed[0].ref


def test_detangle_window_excludes_ancient_pair_far_from_latest(db_session, monkeypatch):
    """A pair far older than the window (relative to the latest txn) is not scanned,
    while a recent pair still is."""
    monkeypatch.setattr(settings, "detangle_scan_window_days", 30)
    u = _user(db_session)
    chk = _account(db_session, u.id, "Checking")
    sav = _account(db_session, u.id, "Savings")
    db_session.add_all([
        # Ancient transfer pair (Jan), far before the latest activity (June).
        ExpenseORM(title="OldXfer", amount=50000, date="2026-01-01",
                   category="Other", account_id=chk.id),
        IncomeORM(title="OldXfer", amount=50000, date="2026-01-02",
                  category="Work", account_id=sav.id),
        # Recent transfer pair sets the anchor to mid-June.
        ExpenseORM(title="NewXfer", amount=70000, date="2026-06-15",
                   category="Other", account_id=chk.id),
        IncomeORM(title="NewXfer", amount=70000, date="2026-06-16",
                  category="Work", account_id=sav.id),
    ])
    db_session.flush()

    created = DetangleService(db_session).run(u.id)
    # Only the recent pair is flagged; the ancient pair is outside the 30d window.
    assert len(created) == 1
    assert "NewXfer".lower() in created[0].message.lower() or \
        "newxfer" in created[0].message.lower()
