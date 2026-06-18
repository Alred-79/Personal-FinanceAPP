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

# Credential tables that carry ``user_id`` but are DELIBERATELY NOT under RLS: they
# are looked up by an unguessable secret hash PRE-authentication (before any tenant
# context exists), so a policy would fail-close those lookups and break login / MCP
# auth. The hash itself is the access control; cross-tenant isolation is meaningless
# for a credential. App-layer queries still scope these by user_id where relevant.
RLS_EXCLUDED_CREDENTIAL_TABLES: frozenset[str] = frozenset(
    {
        "refresh_tokens",  # login/signup/refresh/logout look up by token_hash pre-auth
        "mcp_keys",  # MCP key resolution looks up by key_hash pre-auth
    }
)

# The tenant-owned tables that carry an integer ``user_id`` and get a
# tenant-isolation policy. SINGLE SOURCE OF TRUTH — consumed by BOTH the
# create_all ``after_create`` listener (models.py) and the enable_rls Alembic
# migration, so the list is maintained in exactly one place. ``users`` is the
# owner table (no policy). The 6 children (expenses, income, rule_executions,
# liability_adjustments, import_rows, campaign_progress) reach the user only via
# a parent, so ``user_id`` is denormalized onto them (see the denormalize_user_id
# migration). Non-tenant tables are excluded (category_settings, game_events,
# llm_cache, projection_meta), as are the pre-auth credential tables above. A test
# asserts this list matches every model carrying user_id minus those exclusions.
TENANT_TABLES: tuple[str, ...] = (
    # 29 with a direct user_id column (refresh_tokens + mcp_keys excluded above)
    "accounts",
    "assisted_actions",
    "balance_snapshots",
    "budgets",
    "campaigns",
    "canon_facts",
    "challenges",
    "experiment_exposures",
    "goals",
    "heat_contracts",
    "import_sessions",
    "liabilities",
    "llm_usage",
    "merchant_categories",
    "merchant_lifecycle",
    "merchant_tax_buckets",
    "metric_fade",
    "metric_rollups",
    "mileage_logs",
    "notifications",
    "plans_of_record",
    "rules",
    "runs",
    "scenarios",
    "tax_documents",
    "tax_tags",
    "tokens",
    "used_action_tokens",
    "user_memory",
    # 6 children with user_id denormalized on (WS2 denormalize_user_id migration)
    "campaign_progress",
    "earmarks",  # W7 F4: soft goal sub-buckets; user_id denormalized from the goal
    "expenses",
    "import_rows",
    "income",
    "liability_adjustments",
    "rule_executions",
)

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
