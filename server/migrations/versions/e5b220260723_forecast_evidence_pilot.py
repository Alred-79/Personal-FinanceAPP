"""descriptive forecast evidence pilot

Revision ID: e5b220260723
Revises: d4a120260723
Create Date: 2026-07-23

Adds owner-scoped daily observations and forecast origins. PostgreSQL RLS is
installed explicitly here for already-migrated databases; create-all parity is
provided separately by ``TENANT_TABLES``.
"""

from alembic import op
import sqlalchemy as sa

from server.src.db.rls import enable_rls


revision = "e5b220260723"
down_revision = "d4a120260723"
branch_labels = None
depends_on = None

TABLES = ("forecast_daily_observations", "forecast_evidence_origins")


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def _has_column(bind, table: str, column: str) -> bool:
    if not _has_table(bind, table):
        return False
    return any(item["name"] == column for item in sa.inspect(bind).get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, "accounts", "plaid_balance_refreshed_at"):
        op.add_column(
            "accounts",
            sa.Column(
                "plaid_balance_refreshed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
    if not _has_table(bind, TABLES[0]):
        op.create_table(
            TABLES[0],
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("observed_date", sa.String(), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("total_cents", sa.Integer(), nullable=False),
            sa.Column("account_set_hash", sa.String(), nullable=False),
            sa.Column("account_count", sa.Integer(), nullable=False),
            sa.Column("source_type_counts_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("freshness_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("eligible", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("invalid_reason", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id", "observed_date", name="uq_forecast_observation_user_date"
            ),
        )
        op.create_index(
            "ix_forecast_daily_observations_user_id", TABLES[0], ["user_id"]
        )

    if not _has_table(bind, TABLES[1]):
        op.create_table(
            TABLES[1],
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("origin_date", sa.String(), nullable=False),
            sa.Column("end_date", sa.String(), nullable=False),
            sa.Column("horizon_days", sa.Integer(), nullable=False),
            sa.Column("model_version", sa.String(), nullable=False),
            sa.Column("input_hash", sa.String(), nullable=False),
            sa.Column("account_set_hash", sa.String(), nullable=False),
            sa.Column("predicted_low_cents", sa.Integer(), nullable=False),
            sa.Column("predicted_median_cents", sa.Integer(), nullable=False),
            sa.Column("predicted_high_cents", sa.Integer(), nullable=False),
            sa.Column("overdraft_probability", sa.Float(), nullable=False),
            sa.Column("nominal_coverage", sa.Float(), nullable=True),
            sa.Column("heuristic_widening_ran", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("expected_days", sa.Integer(), nullable=False),
            sa.Column("observed_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("realized_trough_cents", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("reason", sa.String(), nullable=True),
            sa.Column("disjoint_stream", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("matured_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id",
                "origin_date",
                "horizon_days",
                "model_version",
                name="uq_forecast_origin_user_date_horizon_model",
            ),
        )
        op.create_index(
            "ix_forecast_evidence_origins_user_id", TABLES[1], ["user_id"]
        )

    if bind.dialect.name == "postgresql":
        from server.src.settings import settings

        if settings.enable_rls:
            for table in TABLES:
                enable_rls(bind, table)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        if not _has_table(bind, table):
            continue
        if bind.dialect.name == "postgresql":
            op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_index(f"ix_{table}_user_id", table_name=table)
        op.drop_table(table)
    if _has_column(bind, "accounts", "plaid_balance_refreshed_at"):
        op.drop_column("accounts", "plaid_balance_refreshed_at")
