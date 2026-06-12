"""Law-1 integrity harness, used by EVERY v4 package's tests.

``finance_tables_fingerprint`` is a stable hash over all rows of the
financial-truth tables (accounts, expenses, income, budgets, goals, rules,
rule_executions). The pattern in every game test is:

    before = finance_tables_fingerprint(session)
    ...run game code...
    after = finance_tables_fingerprint(session)
    assert before == after   # game code never wrote financial truth

If the hash changes, game code mutated money state — a Law-1 violation.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

# The tables that hold financial truth. Game code must never write to these.
FINANCE_TABLES = (
    "accounts",
    "expenses",
    "income",
    "budgets",
    "goals",
    "rules",
    "rule_executions",
)


def finance_tables_fingerprint(session: Session) -> str:
    """A stable SHA-256 over every row of the financial-truth tables.

    Reads each table's rows ordered by primary key, serialises column values
    deterministically, and hashes the lot. Tables absent from this DB are
    skipped (keeps the helper usable on partial schemas).
    """
    # Inspect via the session's OWN connection, not the engine. On an in-memory
    # SQLite + StaticPool, inspecting the engine opens a second connection that
    # can't see the session's uncommitted (flushed-but-not-committed) rows and
    # disturbs them; the session connection sees the live transaction and leaves
    # it intact.
    conn = session.connection()
    inspector = inspect(conn)
    existing = set(inspector.get_table_names())

    hasher = hashlib.sha256()
    for table in FINANCE_TABLES:
        if table not in existing:
            continue
        columns = [c["name"] for c in inspector.get_columns(table)]
        pk = inspector.get_pk_constraint(table).get("constrained_columns") or [
            columns[0]
        ]
        col_list = ", ".join(columns)
        order = ", ".join(pk)
        rows = session.execute(
            text(f"SELECT {col_list} FROM {table} ORDER BY {order}")
        ).all()
        hasher.update(table.encode())
        for row in rows:
            hasher.update(
                json.dumps(list(row), sort_keys=True, default=str).encode()
            )
    return hasher.hexdigest()
