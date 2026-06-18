"""WS1 type migration: JSON-as-TEXT -> JSONB, naive DateTime -> TIMESTAMPTZ.

Revision ID: b8d2f1a4c6e9
Revises: f2a9c1d4e7b3
Create Date: 2026-06-18

Postgres-only. Brings the alembic-built schema (the historical migrations create
these as ``String``/naive ``DateTime``) into line with the create_all schema,
which now uses ``JSONStr`` (→ JSONB) and ``DateTime(timezone=True)`` (→ TIMESTAMPTZ)
from server/src/db/models.py. On an EMPTY Postgres DB these ALTERs are instant; on
a populated DB they convert existing rows (JSON text → jsonb, naive stamps → UTC).

SQLite is untouched: its historical String/DateTime columns are already correct,
and the ``JSONStr``/``DateTime`` variants are no-ops there.

The column lists are hardcoded (not introspected from live metadata) so this
migration is an immutable snapshot that does not drift when models.py changes.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b8d2f1a4c6e9"
down_revision: Union[str, Sequence[str]] = "f2a9c1d4e7b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, default_literal | None) — the JSON-as-TEXT columns that become
# JSONB. Mirrors the ``JSONStr`` columns in models.py. The default literal is the
# SQL ``server_default`` the historical migration gave the column (re-applied as
# jsonb); ``None`` means the column had no SQL default.
_JSON_COLUMNS = [
    ("assisted_actions", "how_json", "{}"),
    ("rules", "conditions", "[]"),
    ("rules", "action_params", "{}"),
    ("runs", "map_json", None),
    ("runs", "overlay_json", "{}"),
    ("runs", "score_json", None),
    ("challenges", "params_json", "{}"),
    ("challenges", "verdict_json", None),
    ("scenarios", "overlay_json", "{}"),
    ("plans_of_record", "rule_ids_json", "[]"),
    ("plans_of_record", "baseline_snapshot_json", None),
    ("tax_documents", "fields_json", "{}"),
]

# (table, column) — naive-timestamp stamp columns that become TIMESTAMPTZ. Mirrors
# the ``DateTime(timezone=True)`` columns in models.py. Financial date-only ISO
# strings and the String-ISO timestamp columns are deliberately NOT here.
_TS_COLUMNS = [
    ("accounts", "last_updated"),
    ("refresh_tokens", "expires_at"),
    ("refresh_tokens", "created_at"),
    ("merchant_categories", "updated_at"),
    ("notifications", "created_at"),
    ("used_action_tokens", "created_at"),
    ("rules", "created_at"),
    ("rule_executions", "fired_at"),
    ("mcp_keys", "created_at"),
    ("mcp_keys", "last_used_at"),
    ("mcp_keys", "expires_at"),
    ("mcp_keys", "revoked_at"),
    ("liabilities", "opened_at"),
    ("liabilities", "defeated_at"),
    ("heat_contracts", "created_at"),
    ("liability_adjustments", "created_at"),
    ("challenges", "created_at"),
    ("scenarios", "created_at"),
    ("scenarios", "updated_at"),
    ("plans_of_record", "committed_at"),
    ("plans_of_record", "last_checked_at"),
    ("import_sessions", "created_at"),
    ("import_sessions", "committed_at"),
    ("tax_tags", "created_at"),
    ("tax_tags", "updated_at"),
    ("merchant_tax_buckets", "updated_at"),
    ("tax_documents", "created_at"),
    ("tax_documents", "confirmed_at"),
    ("mileage_logs", "created_at"),
]


def _drop_runs_map_trigger() -> None:
    # runs_map_json_immutable is BEFORE UPDATE OF map_json, so PG refuses to alter
    # map_json's type ("cannot alter type of a column used in a trigger
    # definition") until the trigger is dropped. The function is column-agnostic
    # and stays. Recreated by _recreate_runs_map_trigger after the ALTER.
    op.execute("DROP TRIGGER IF EXISTS runs_map_json_immutable ON runs")


def _recreate_runs_map_trigger() -> None:
    op.execute(
        "CREATE TRIGGER runs_map_json_immutable BEFORE UPDATE OF map_json ON runs "
        "FOR EACH ROW EXECUTE FUNCTION runs_map_json_immutable_fn()"
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # Naive stamps are conceptually UTC (docs/TIMEZONE-AUDIT.md); the explicit
    # ``AT TIME ZONE 'UTC'`` below interprets them as such on cast.
    op.execute("SET TIME ZONE 'UTC'")
    _drop_runs_map_trigger()
    for table, col, default in _JSON_COLUMNS:
        # DROP DEFAULT is a safe no-op when the column has none. Pre-clean '' → NULL
        # so a stray empty string doesn't fail the ::jsonb cast.
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {col} DROP DEFAULT")
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {col} TYPE jsonb "
            f"USING NULLIF({col}, '')::jsonb"
        )
        if default is not None:
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN {col} SET DEFAULT '{default}'::jsonb"
            )
    for table, col in _TS_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {col} TYPE timestamptz "
            f"USING {col} AT TIME ZONE 'UTC'"
        )
    _recreate_runs_map_trigger()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _drop_runs_map_trigger()
    for table, col in _TS_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {col} TYPE timestamp "
            f"USING {col} AT TIME ZONE 'UTC'"
        )
    for table, col, default in reversed(_JSON_COLUMNS):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {col} DROP DEFAULT")
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {col} TYPE varchar USING {col}::text"
        )
        if default is not None:
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN {col} SET DEFAULT '{default}'"
            )
    _recreate_runs_map_trigger()
