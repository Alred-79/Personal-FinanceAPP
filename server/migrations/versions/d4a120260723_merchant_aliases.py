"""flat reversible merchant aliases

Revision ID: d4a120260723
Revises: b8f720260720
Create Date: 2026-07-23

Adds a tenant-owned, user-confirmed sidecar. Upgrade explicitly installs the
PostgreSQL tenant policy even when ``create_all`` already created the table;
downgrade removes that policy before dropping the table.
"""

from alembic import op
import sqlalchemy as sa


revision = "d4a120260723"
down_revision = "b8f720260720"
branch_labels = None
depends_on = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def _install_postgres_rls(bind) -> None:
    if bind.dialect.name != "postgresql":
        return
    from server.src.settings import settings

    if not settings.enable_rls:
        return
    op.execute("ALTER TABLE merchant_aliases ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE merchant_aliases FORCE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS merchant_aliases_tenant_isolation "
        "ON merchant_aliases"
    )
    op.execute(
        "CREATE POLICY merchant_aliases_tenant_isolation ON merchant_aliases "
        "USING (user_id = NULLIF(current_setting('app.user_id', true), '')::int) "
        "WITH CHECK (user_id = "
        "NULLIF(current_setting('app.user_id', true), '')::int)"
    )


def _drop_postgres_rls(bind) -> None:
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "DROP POLICY IF EXISTS merchant_aliases_tenant_isolation "
        "ON merchant_aliases"
    )
    op.execute("ALTER TABLE merchant_aliases NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE merchant_aliases DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "merchant_aliases"):
        op.create_table(
            "merchant_aliases",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("alias_key", sa.String(), nullable=False),
            sa.Column("canonical_key", sa.String(), nullable=False),
            sa.Column("canonical_label", sa.String(), nullable=False),
            sa.Column("source", sa.String(), nullable=False, server_default="user"),
            sa.Column("active", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=True,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id", "alias_key", name="uq_merchant_alias_user_key"
            ),
        )
        op.create_index(
            "ix_merchant_aliases_user_id",
            "merchant_aliases",
            ["user_id"],
            unique=False,
        )
    _install_postgres_rls(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "merchant_aliases"):
        _drop_postgres_rls(bind)
        op.drop_index("ix_merchant_aliases_user_id", table_name="merchant_aliases")
        op.drop_table("merchant_aliases")
