"""``mcp_audit_log`` is append-only — enforced, not asserted.

The model docstring called this table "append-only" long before anything made it
so: there were no triggers on it in ``models.py`` or in any migration, unlike
``game_events`` (models.py) which has had real SQLite + Postgres trigger pairs
all along. An audit trail whose immutability lives only in a docstring is a
comment, not a control — and this is the one table whose whole purpose is to be
believed later.

The threat these tests pin down is specific: rewriting a recorded *denial* into
an allow, or deleting the record of a read that happened. Both must abort at the
database, below any application code that might one day try.

Mirrors ``test_game_substrate.py::test_raw_update_and_delete_are_blocked_by_trigger``,
including its Postgres gotcha — target the row's REAL id, never a hardcoded 1,
because PG sequences don't roll back and a ``WHERE id=1`` would match no row and
never fire a FOR EACH ROW trigger.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from server.src.db.models import MCPAuditLog, User as UserORM


def _seed_denial(db_session) -> int:
    """One recorded denial — the row an attacker would most want to rewrite."""
    db_session.add(
        UserORM(
            id=1,
            username="alice",
            full_name="Alice",
            email="a@x.com",
            hashed_password="h",
        )
    )
    db_session.flush()
    db_session.add(
        MCPAuditLog(
            user_id=1,
            key_id=3,
            resource="read:accounts",
            decision="deny:missing_scope",
            latency_ms=4.2,
            params_hash="abc123def456",
        )
    )
    db_session.flush()
    return db_session.execute(text("SELECT id FROM mcp_audit_log")).scalar()


def test_rewriting_a_denial_into_an_allow_is_blocked(db_session):
    """History cannot be laundered: UPDATE aborts at the DB."""
    rid = _seed_denial(db_session)
    with pytest.raises(Exception):
        db_session.execute(
            text("UPDATE mcp_audit_log SET decision='allow' WHERE id=:i"),
            {"i": rid},
        )
        db_session.flush()
    db_session.rollback()


def test_deleting_an_audit_row_is_blocked(db_session):
    """A read that happened cannot be un-recorded: DELETE aborts at the DB."""
    rid = _seed_denial(db_session)
    with pytest.raises(Exception):
        db_session.execute(
            text("DELETE FROM mcp_audit_log WHERE id=:i"), {"i": rid}
        )
        db_session.flush()
    db_session.rollback()


def test_appending_still_works(db_session):
    """The guard blocks mutation only — the table must still accept new rows,
    or the trigger would have silently disabled auditing altogether."""
    _seed_denial(db_session)
    db_session.add(
        MCPAuditLog(
            user_id=1,
            key_id=3,
            resource="read:transactions",
            decision="allow",
            latency_ms=9.1,
            params_hash="0011223344556677",
        )
    )
    db_session.flush()
    assert (
        db_session.execute(text("SELECT count(*) FROM mcp_audit_log")).scalar() == 2
    )
