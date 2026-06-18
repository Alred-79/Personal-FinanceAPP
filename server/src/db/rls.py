"""Row-Level Security helpers (WS2) — Postgres-only; no-ops elsewhere.

Tenant isolation is enforced in the database, not just in query ``WHERE`` clauses:
each tenant table gets RLS ENABLEd and FORCEd (so even the table owner is subject
to it) with a policy keyed on the ``app.user_id`` GUC. The request binds that GUC
per transaction via ``set_tenant``.

``set_tenant`` MUST use a transaction-scoped binding (``set_config(..., is_local=
true)`` == ``SET LOCAL``). On a pooled / PgBouncer connection a *session*-scoped
``SET`` would leak one user's context into the next request that reuses the
connection; a transaction-scoped one cannot. The policy reads the GUC with
``current_setting('app.user_id', true)`` (missing_ok=true) so an UNSET context
yields NULL and matches no rows — RLS fails closed, never "see everything".

This module provides the mechanism + a reusable ``enable_rls(table)``. Rolling it
out across every tenant table (and wiring ``set_tenant`` into the request
lifecycle) is the remaining WS2 migration — see docs/MULTI-TENANT-DO-NOW.md.
"""

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

# Custom GUC name (must be namespaced — contain a dot — to be settable without a
# prior definition).
TENANT_GUC = "app.user_id"

_ENABLE_RLS_SQL = (
    "ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}",
    # NULLIF(..., '') is load-bearing: once a custom GUC has been SET LOCAL in a
    # session, it reverts to '' (empty string), NOT unset, when the transaction
    # ends — so a bare ``current_setting(...)::int`` would raise on '' instead of
    # failing closed. NULLIF maps '' (and an unset GUC) to NULL, and
    # ``user_id = NULL`` matches no rows. (Found via the Postgres RLS test.)
    (
        "CREATE POLICY {table}_tenant_isolation ON {table} "
        "USING (user_id = NULLIF(current_setting('app.user_id', true), '')::int) "
        "WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::int)"
    ),
)


def enable_rls(connection: Connection, table: str) -> None:
    """Enable + force RLS with the tenant-isolation policy on ``table``.

    Postgres-only DDL; call behind a dialect check. The table must have an
    integer ``user_id`` column.
    """
    if connection.dialect.name != "postgresql":
        return
    for stmt in _ENABLE_RLS_SQL:
        connection.execute(text(stmt.format(table=table)))


def set_tenant(session: Session, user_id) -> None:
    """Bind the current transaction to a tenant (Postgres); no-op elsewhere.

    Transaction-scoped (``SET LOCAL`` semantics) so it cannot leak across
    requests sharing a pooled connection.
    """
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    session.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(int(user_id))},
    )
