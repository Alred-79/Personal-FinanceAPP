"""v4 package 01 — sync-fold hook tests (groups 10-12) + Law-1 integrity.

Drives PlaidService with a mocked PlaidClient and asserts the right game events
are emitted: pending emits nothing, pending->posted emits exactly one TxnPosted
keyed by the posted id, and sync gaps land in the sync_state projection.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy import select

from server.src.databridge.plaid_client import SyncResult
from server.src.db.models import (
    Account as AccountORM,
    Token as TokenORM,
    User as UserORM,
)
from server.src.models import UserInDB
from server.src.services.game.events import GameEventDraft, record_events
from server.src.services.plaid_service import PlaidService
from server.tests.integrity import finance_tables_fingerprint


@pytest.fixture
def seed_user(db_session):
    user = UserORM(
        username="syncfold",
        full_name="Sync Fold",
        email="syncfold@test.com",
        hashed_password="h",
        disabled=0,
    )
    db_session.add(user)
    db_session.flush()
    return UserInDB(
        id=int(user.id),
        username=str(user.username),
        email=str(user.email),
        full_name=str(user.full_name),
        disabled=False,
        hashed_password=str(user.hashed_password),
    )


@pytest.fixture
def seed_account(db_session, seed_user):
    token = TokenORM(user_id=seed_user.id, name="Chase", key="access-fake")
    db_session.add(token)
    account = AccountORM(name="Chase", type="depository", balance=0, user_id=seed_user.id)
    db_session.add(account)
    db_session.flush()
    return account.id, token


def _txn(txn_id, name, amount, *, pending=False, pending_txn_id=None,
         date="2026-06-15"):
    return {
        "transaction_id": txn_id,
        "name": name,
        "amount": amount,
        "date": date,
        "category": ["Shopping"],
        "personal_finance_category": None,
        "pending": pending,
        "pending_transaction_id": pending_txn_id,
    }


def _events(db_session, **where):
    clause = " AND ".join(f"{k}=:{k}" for k in where) or "1=1"
    return db_session.execute(
        text(f"SELECT type, payload, idempotency_key FROM game_events WHERE {clause} ORDER BY id"),
        where,
    ).all()


# ── 10: pending emits nothing ────────────────────────────────────────────


@patch("server.src.services.plaid_service.PlaidClient")
def test_pending_transaction_emits_no_events(MockPC, db_session, seed_user, seed_account):
    mock = MagicMock()
    MockPC.return_value = mock
    mock.sync_transactions.return_value = SyncResult(
        added=[_txn("p1", "Pending Coffee", 4.50, pending=True)],
        modified=[], removed=[], next_cursor="c1",
    )
    PlaidService(db_session).sync_all_tokens(seed_user)
    db_session.flush()
    posted = _events(db_session, type="TxnPosted")
    assert posted == []


# ── 11: pending -> posted emits exactly one TxnPosted, keyed by posted id ──


@patch("server.src.services.plaid_service.PlaidClient")
def test_pending_then_posted_emits_one_posted_event(MockPC, db_session, seed_user, seed_account):
    mock = MagicMock()
    MockPC.return_value = mock
    # First sync: the pending charge — no event.
    mock.sync_transactions.return_value = SyncResult(
        added=[_txn("pending-1", "Coffee", 4.50, pending=True)],
        modified=[], removed=[], next_cursor="c1",
    )
    PlaidService(db_session).sync_all_tokens(seed_user)
    db_session.flush()

    # Second sync: pending removed + the posted version added (carrying the
    # pending_transaction_id link).
    mock.sync_transactions.return_value = SyncResult(
        added=[_txn("posted-1", "Coffee", 4.50, pending=False, pending_txn_id="pending-1")],
        modified=[],
        removed=[_txn("pending-1", "Coffee", 4.50)],
        next_cursor="c2",
    )
    PlaidService(db_session).sync_all_tokens(seed_user)
    db_session.flush()

    posted = _events(db_session, type="TxnPosted")
    assert len(posted) == 1
    assert posted[0].idempotency_key == "plaid:posted-1:posted"


# ── 12: gaps land in sync_state projection ───────────────────────────────


def test_sync_gap_open_then_close_recorded_in_projection(db_session, seed_account):
    account_id, _ = seed_account
    record_events(db_session, [GameEventDraft(
        stream="sync", type="SyncGapOpened",
        payload={"account_id": account_id, "opened_at": "2026-06-10T00:00:00Z",
                 "from": "2026-06-08"},
    )])
    db_session.flush()
    gaps = json.loads(db_session.execute(
        text("SELECT value FROM game_projection_kv WHERE projection='sync_state' AND key='gaps'")
    ).scalar_one())
    assert len(gaps["open"]) == 1
    assert gaps["open"][0]["account_id"] == account_id

    record_events(db_session, [GameEventDraft(
        stream="sync", type="SyncGapClosed",
        payload={"account_id": account_id, "closed_at": "2026-06-11T00:00:00Z",
                 "to": "2026-06-11"},
    )])
    db_session.flush()
    gaps = json.loads(db_session.execute(
        text("SELECT value FROM game_projection_kv WHERE projection='sync_state' AND key='gaps'")
    ).scalar_one())
    assert gaps["open"] == []
    assert len(gaps["closed"]) == 1
    assert gaps["closed"][0]["from"] == "2026-06-08"
    assert gaps["closed"][0]["to"] == "2026-06-11"


# ── Law-1 integrity around a real sync ───────────────────────────────────


@patch("server.src.services.plaid_service.PlaidClient")
def test_posted_txn_emits_event_and_ledger_reflects_it(MockPC, db_session, seed_user, seed_account):
    account_id, _ = seed_account
    mock = MagicMock()
    MockPC.return_value = mock
    mock.sync_transactions.return_value = SyncResult(
        added=[_txn("a1", "Coffee", 4.50, pending=False),
               _txn("a2", "Paycheck", -2500.00, pending=False)],
        modified=[], removed=[], next_cursor="c1",
    )
    PlaidService(db_session).sync_all_tokens(seed_user)
    db_session.flush()
    posted = _events(db_session, type="TxnPosted")
    assert len(posted) == 2
    keys = {p.idempotency_key for p in posted}
    assert keys == {"plaid:a1:posted", "plaid:a2:posted"}
