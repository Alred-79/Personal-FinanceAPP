"""Reconciliation Desk pipeline — extract → normalize → categorize → dedup →
reconcile → persist. The model calls are injected fakes (no Groq), mirroring
test_receipts. The headline assertions are the balance-check loop: a clean
statement reconciles; a tampered one localizes the offending row.
"""

from sqlalchemy import select

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
    ImportRow as ImportRowORM,
    ImportSession as ImportSessionORM,
    User as UserORM,
)
from server.src.services.reconciliation_service import ReconciliationService


# ── fixtures ────────────────────────────────────────────────────────────────

def _user(db, username="alice"):
    u = UserORM(
        username=username, full_name="Alice", email=f"{username}@e.com", hashed_password="x"
    )
    db.add(u)
    db.flush()
    return u


def _account(db, user_id, name="Checking"):
    a = AccountORM(name=name, type="depository", balance=0, user_id=user_id)
    db.add(a)
    db.flush()
    return a


def _svc(db, statement):
    """A service whose vision_fn returns *statement* and never calls an LLM."""
    return ReconciliationService(
        db,
        vision_fn=lambda b64, ct: statement,
        text_llm_fn=lambda txt: statement,
        # No-op categorizer LLM so unknowns fall to "Other" without a network call.
    )


def _ingest(svc, user_id, account_id, source_kind="image"):
    return svc.ingest(
        user_id=user_id,
        account_id=account_id,
        source_kind=source_kind,
        raw_bytes=b"fake-image-bytes",
        content_type="image/png",
    )


# A clean statement: opening 1000.00, two debits and a credit, closing 1075.50.
# -50.00 - 24.50 + 150.00 = +75.50  →  1000.00 + 75.50 = 1075.50 ✓
CLEAN = {
    "opening_balance": 1000.00,
    "closing_balance": 1075.50,
    "period": "March 2026",
    "transactions": [
        {"date": "2026-03-02", "description": "Whole Foods", "amount": -50.00, "running_balance": 950.00},
        {"date": "2026-03-05", "description": "Starbucks #12", "amount": -24.50, "running_balance": 925.50},
        {"date": "2026-03-10", "description": "Payroll", "amount": 150.00, "running_balance": 1075.50},
    ],
}


# ── the balance check ────────────────────────────────────────────────────────

def test_clean_statement_reconciles(db_session):
    u = _user(db_session)
    a = _account(db_session, u.id)
    session = _ingest(_svc(db_session, CLEAN), u.id, a.id)

    assert session.reconciled == 1
    assert session.discrepancy_cents == 0
    assert session.opening_balance == 100000  # cents
    assert session.closing_balance == 107550
    rows = db_session.execute(
        select(ImportRowORM).where(ImportRowORM.session_id == session.id)
    ).scalars().all()
    assert len(rows) == 3
    assert all(r.status != "exception" for r in rows)
    assert all(r.included == 1 for r in rows)


def test_missing_row_breaks_global_balance(db_session):
    # Drop the credit: now -50 -24.50 = -74.50, but closing still says +75.50.
    broken = {**CLEAN, "transactions": CLEAN["transactions"][:2]}
    u = _user(db_session)
    a = _account(db_session, u.id)
    session = _ingest(_svc(db_session, broken), u.id, a.id)

    assert session.reconciled == 0
    # expected (closing-opening)=+7550c; actual -7450c; discrepancy = 15000c.
    assert session.discrepancy_cents == 15000


def test_running_balance_mismatch_localizes_the_bad_row(db_session):
    # Tamper the SECOND row's amount (-24.50 → -34.50) but leave its running
    # balance at 925.50. The per-row walk should flag exactly that row.
    tampered = {
        **CLEAN,
        "transactions": [
            CLEAN["transactions"][0],
            {**CLEAN["transactions"][1], "amount": -34.50},
            CLEAN["transactions"][2],
        ],
    }
    u = _user(db_session)
    a = _account(db_session, u.id)
    session = _ingest(_svc(db_session, tampered), u.id, a.id)

    rows = db_session.execute(
        select(ImportRowORM).where(ImportRowORM.session_id == session.id).order_by(ImportRowORM.id)
    ).scalars().all()
    flagged = [r for r in rows if r.status == "exception"]
    assert len(flagged) == 1
    assert flagged[0].title == "Starbucks #12"
    assert flagged[0].reason == "running_balance_mismatch"
    assert flagged[0].included == 0  # exceptions start excluded


def test_row_missing_amount_is_an_exception(db_session):
    blank = {
        "opening_balance": 100.0,
        "closing_balance": 50.0,
        "transactions": [
            {"date": "2026-03-01", "description": "Mystery", "amount": None, "running_balance": None},
            {"date": "2026-03-02", "description": "Rent", "amount": -50.0, "running_balance": 50.0},
        ],
    }
    u = _user(db_session)
    a = _account(db_session, u.id)
    session = _ingest(_svc(db_session, blank), u.id, a.id)
    rows = db_session.execute(
        select(ImportRowORM).where(ImportRowORM.session_id == session.id)
    ).scalars().all()
    exc = [r for r in rows if r.status == "exception"]
    assert len(exc) == 1 and exc[0].reason == "missing_field"


# ── dedup against existing transactions ──────────────────────────────────────

def test_dedup_flags_existing_transaction(db_session):
    u = _user(db_session)
    a = _account(db_session, u.id)
    # Pre-existing expense that matches the first statement row.
    db_session.add(
        ExpenseORM(
            title="Whole Foods", amount=5000, date="2026-03-02",
            category="Shops", account_id=a.id,
        )
    )
    db_session.flush()

    session = _ingest(_svc(db_session, CLEAN), u.id, a.id)
    rows = db_session.execute(
        select(ImportRowORM).where(ImportRowORM.session_id == session.id)
    ).scalars().all()
    dupes = [r for r in rows if r.status == "duplicate"]
    assert len(dupes) == 1
    assert dupes[0].title == "Whole Foods"
    assert dupes[0].included == 0  # duplicates start excluded
    assert dupes[0].match_ref is not None
    # A flagged duplicate is still part of the statement sum, so the statement
    # still reconciles overall.
    assert session.reconciled == 1


def test_statement_without_balances_still_persists_rows(db_session):
    # CSV-like input: no opening/closing → can't reconcile, but rows still land.
    no_bal = {
        "opening_balance": None,
        "closing_balance": None,
        "transactions": [
            {"date": "2026-03-01", "description": "Coffee", "amount": -4.0, "running_balance": None},
        ],
    }
    u = _user(db_session)
    a = _account(db_session, u.id)
    session = _ingest(_svc(db_session, no_bal), u.id, a.id)
    assert session.reconciled == 0  # nothing to reconcile against
    assert session.discrepancy_cents == 0
    rows = db_session.execute(
        select(ImportRowORM).where(ImportRowORM.session_id == session.id)
    ).scalars().all()
    assert len(rows) == 1 and rows[0].included == 1


def test_foreign_account_is_rejected(db_session):
    u1 = _user(db_session, "alice")
    u2 = _user(db_session, "bob")
    a2 = _account(db_session, u2.id)
    svc = _svc(db_session, CLEAN)
    try:
        _ingest(svc, u1.id, a2.id)
        assert False, "expected ValueError for foreign account"
    except ValueError:
        pass


# ── commit ───────────────────────────────────────────────────────────────────

def test_commit_creates_transactions_with_import_row_id(db_session):
    u = _user(db_session)
    a = _account(db_session, u.id)
    svc = _svc(db_session, CLEAN)
    session = _ingest(svc, u.id, a.id)
    result = svc.commit_session(u.id, session.id)

    # CLEAN has 2 debits + 1 credit, all clean → 3 committed.
    assert result["committed"] == 3
    expenses = db_session.execute(
        select(ExpenseORM).where(ExpenseORM.account_id == a.id)
    ).scalars().all()
    incomes = db_session.execute(
        select(IncomeORM).where(IncomeORM.account_id == a.id)
    ).scalars().all()
    assert len(expenses) == 2 and len(incomes) == 1
    assert all(e.import_row_id is not None for e in expenses)
    assert all(i.import_row_id is not None for i in incomes)

    db_session.refresh(session)
    assert session.status == "committed"
    # Account balance moved by the net statement delta (+75.50 → 7550 cents).
    db_session.refresh(a)
    assert a.balance == 7550


def test_commit_skips_excluded_and_exception_rows(db_session):
    # One row is an exception (missing amount) → must not be committed.
    blank = {
        "opening_balance": 100.0,
        "closing_balance": 50.0,
        "transactions": [
            {"date": "2026-03-01", "description": "Mystery", "amount": None, "running_balance": None},
            {"date": "2026-03-02", "description": "Rent", "amount": -50.0, "running_balance": 50.0},
        ],
    }
    u = _user(db_session)
    a = _account(db_session, u.id)
    svc = _svc(db_session, blank)
    session = _ingest(svc, u.id, a.id)
    result = svc.commit_session(u.id, session.id)
    assert result["committed"] == 1  # only Rent
    expenses = db_session.execute(
        select(ExpenseORM).where(ExpenseORM.account_id == a.id)
    ).scalars().all()
    assert [e.title for e in expenses] == ["Rent"]


def test_commit_is_idempotent_per_session(db_session):
    u = _user(db_session)
    a = _account(db_session, u.id)
    svc = _svc(db_session, CLEAN)
    session = _ingest(svc, u.id, a.id)
    svc.commit_session(u.id, session.id)

    # Re-committing a session that's no longer pending must raise, not double-write.
    try:
        svc.commit_session(u.id, session.id)
        assert False, "expected ValueError on re-commit"
    except ValueError:
        pass
    # Still exactly 3 transactions.
    total = db_session.execute(
        select(ExpenseORM).where(ExpenseORM.account_id == a.id)
    ).scalars().all()
    assert len(total) == 2  # 2 expenses (the third is income)


def test_commit_foreign_session_rejected(db_session):
    u1 = _user(db_session, "alice")
    u2 = _user(db_session, "bob")
    a1 = _account(db_session, u1.id)
    svc = _svc(db_session, CLEAN)
    session = _ingest(svc, u1.id, a1.id)
    try:
        svc.commit_session(u2.id, session.id)
        assert False, "expected ValueError for foreign session"
    except ValueError:
        pass
