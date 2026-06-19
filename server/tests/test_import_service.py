"""Import Anything — classify + dispatch. The classifier and extractors are
injected fakes, so each routing path (statement / feed / receipt / unknown) is
asserted without any Groq call.
"""

from sqlalchemy import select

from server.src.db.models import (
    Account as AccountORM,
    ImportRow as ImportRowORM,
    User as UserORM,
)
from server.src.services.import_service import ImportService, _kind_of
from server.src.services.reconciliation_service import ReconciliationService


def _user(db, username="alice"):
    u = UserORM(
        username=username, full_name="A", email=f"{username}@e.com", hashed_password="x"
    )
    db.add(u)
    db.flush()
    return u


def _account(db, user_id):
    a = AccountORM(name="Checking", type="depository", balance=0, user_id=user_id)
    db.add(a)
    db.flush()
    return a


STATEMENT = {
    "opening_balance": 100.0,
    "closing_balance": 50.0,
    "transactions": [
        {"date": "2026-03-01", "description": "Rent", "amount": -50.0, "running_balance": 50.0},
    ],
}

FEED = {
    "opening_balance": None,
    "closing_balance": None,
    "transactions": [
        {"date": "2026-03-01", "description": "Venmo to Sam", "amount": -20.0, "running_balance": None},
        {"date": "2026-03-02", "description": "Venmo from Lee", "amount": 15.0, "running_balance": None},
    ],
}


def _svc(db, kind, statement):
    """ImportService whose classifier returns *kind* and whose reconciliation
    extractor returns *statement*."""
    recon = ReconciliationService(
        db, vision_fn=lambda b64, ct: statement, text_llm_fn=lambda t: statement
    )
    return ImportService(
        db,
        classify_fn=lambda text, b64, ct: kind,
        reconciliation=recon,
    )


# ── _kind_of parsing ─────────────────────────────────────────────────────────

def test_kind_of_parses_and_defaults():
    assert _kind_of('{"kind": "statement"}') == "statement"
    assert _kind_of('{"kind": "FEED"}') == "feed"
    assert _kind_of('{"kind": "nonsense"}') == "unknown"
    assert _kind_of("not json") == "unknown"
    assert _kind_of(None) == "unknown"


# ── routing ──────────────────────────────────────────────────────────────────

def test_statement_routes_through_reconciliation(db_session):
    u = _user(db_session)
    a = _account(db_session, u.id)
    svc = _svc(db_session, "statement", STATEMENT)
    session, kind = svc.ingest_any(
        user_id=u.id, account_id=a.id, raw_bytes=b"img", content_type="image/png"
    )
    assert kind == "statement"
    assert session.reconciled == 1  # 100 - 50 == 50 ✓
    rows = db_session.execute(
        select(ImportRowORM).where(ImportRowORM.session_id == session.id)
    ).scalars().all()
    assert len(rows) == 1


def test_feed_routes_through_balance_less_pipeline(db_session):
    u = _user(db_session)
    a = _account(db_session, u.id)
    svc = _svc(db_session, "feed", FEED)
    session, kind = svc.ingest_any(
        user_id=u.id, account_id=a.id, raw_bytes=b"img", content_type="image/png"
    )
    assert kind == "feed"
    assert session.reconciled == 0  # no balances to reconcile against
    rows = db_session.execute(
        select(ImportRowORM).where(ImportRowORM.session_id == session.id)
    ).scalars().all()
    assert len(rows) == 2
    assert all(r.included == 1 for r in rows)


def test_unknown_still_extracts_as_feed(db_session):
    u = _user(db_session)
    a = _account(db_session, u.id)
    svc = _svc(db_session, "unknown", FEED)
    session, kind = svc.ingest_any(
        user_id=u.id, account_id=a.id, raw_text="some pasted blob"
    )
    assert kind == "unknown"
    rows = db_session.execute(
        select(ImportRowORM).where(ImportRowORM.session_id == session.id)
    ).scalars().all()
    assert len(rows) == 2  # best-effort extraction still yields rows


def test_receipt_routes_to_single_row_session(db_session, monkeypatch):
    u = _user(db_session)
    a = _account(db_session, u.id)
    # Patch the receipt scanner the import service lazily imports.
    from server.src.services import receipt_service

    monkeypatch.setattr(
        receipt_service,
        "_default_vision_fn",
        lambda b64, ct: {
            "merchant": "Target",
            "total": 42.17,
            "date": "2026-05-03",
            "category": "Shops",
            "line_items": [],
        },
    )
    svc = ImportService(db_session, classify_fn=lambda t, b, c: "receipt")
    session, kind = svc.ingest_any(
        user_id=u.id, account_id=a.id, raw_bytes=b"img", content_type="image/png"
    )
    assert kind == "receipt"
    rows = db_session.execute(
        select(ImportRowORM).where(ImportRowORM.session_id == session.id)
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "Target"
    assert rows[0].amount == -4217  # expense (money out), cents
    assert rows[0].category == "Shops"


def test_foreign_account_rejected(db_session):
    u1 = _user(db_session, "alice")
    u2 = _user(db_session, "bob")
    a2 = _account(db_session, u2.id)
    svc = _svc(db_session, "statement", STATEMENT)
    try:
        svc.ingest_any(
            user_id=u1.id, account_id=a2.id, raw_bytes=b"img", content_type="image/png"
        )
        assert False, "expected ValueError"
    except ValueError:
        pass


# ── E2: amount bounds + row cap ──────────────────────────────────────────────


def test_out_of_range_amount_becomes_exception_row(db_session):
    """An extracted amount beyond the ±1e12 money bound (or non-finite) is NOT
    imported as a silent 0 — it surfaces as an excluded exception row tagged
    reason='out_of_range', distinct from a simply-missing amount."""
    u = _user(db_session)
    a = _account(db_session, u.id)
    statement = {
        "opening_balance": None,
        "closing_balance": None,
        "transactions": [
            {"date": "2026-03-01", "description": "Sane", "amount": -12.50},
            {"date": "2026-03-02", "description": "Absurd", "amount": 1e308},
            {"date": "2026-03-03", "description": "TooBig", "amount": 5_000_000_000_000},
        ],
    }
    svc = _svc(db_session, "feed", statement)
    session, _ = svc.ingest_any(
        user_id=u.id, account_id=a.id, raw_bytes=b"img", content_type="image/png"
    )
    rows = db_session.execute(
        select(ImportRowORM).where(ImportRowORM.session_id == session.id)
    ).scalars().all()
    by_title = {r.title: r for r in rows}
    assert by_title["Sane"].status != "exception"  # the normal row imports
    for bad in ("Absurd", "TooBig"):
        assert by_title[bad].status == "exception"
        assert by_title[bad].reason == "out_of_range"
        assert by_title[bad].included == 0  # never auto-included
        assert by_title[bad].amount == 0  # not an invented figure


def test_over_cap_document_is_truncated_with_flag(db_session):
    """A document exceeding the row cap is truncated — a truthful excluded marker
    row surfaces the omitted count rather than silently dropping or OOM-ing."""
    from server.src.services.reconciliation_service import MAX_EXTRACTION_ROWS

    u = _user(db_session)
    a = _account(db_session, u.id)
    n = MAX_EXTRACTION_ROWS + 5
    statement = {
        "opening_balance": None,
        "closing_balance": None,
        "transactions": [
            {"date": "2026-03-01", "description": f"r{i}", "amount": -1.0}
            for i in range(n)
        ],
    }
    svc = _svc(db_session, "feed", statement)
    session, _ = svc.ingest_any(
        user_id=u.id, account_id=a.id, raw_bytes=b"img", content_type="image/png"
    )
    rows = db_session.execute(
        select(ImportRowORM).where(ImportRowORM.session_id == session.id)
    ).scalars().all()
    truncation_markers = [r for r in rows if r.reason == "truncated"]
    assert len(truncation_markers) == 1
    assert "5 more rows omitted" in truncation_markers[0].title
    assert truncation_markers[0].included == 0
    # The real rows are capped (cap data rows + the 1 marker).
    data_rows = [r for r in rows if r.reason != "truncated"]
    assert len(data_rows) == MAX_EXTRACTION_ROWS
