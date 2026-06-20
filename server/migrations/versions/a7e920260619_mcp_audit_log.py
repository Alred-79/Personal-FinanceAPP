"""Agent Vault — add mcp_audit_log (persisted MCP read/denial trail)

Revision ID: a7e920260619
Revises: f5d620260619
Create Date: 2026-06-19

The MCP audit trail used to be log-only (a MEDIUM finding). This table persists
one row per resolved read (and per resolvable denial) so the owner's Agent Vault
can show what an external agent actually did. Privacy-preserving by construction:
only a truncated ``params_hash`` is stored — never raw parameter values, never any
financial detail. RLS-scoped to the owner like any tenant table (mirrors the
enable_rls migration + create_all listener; same helper/list). Idempotent.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7e920260619"
down_revision = "f5d620260619"
branch_labels = None
depends_on = None

_TABLE = "mcp_audit_log"


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, _TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key_id", sa.Integer(), nullable=True),
        sa.Column("resource", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("params_hash", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index("ix_mcp_audit_log_user_id", _TABLE, ["user_id"])
    op.create_index("ix_mcp_audit_log_created_at", _TABLE, ["created_at"])

    # Install tenant isolation when the deployment opted into RLS (Postgres only).
    if bind.dialect.name == "postgresql":
        from server.src.db.rls import enable_rls
        from server.src.settings import settings

        if settings.enable_rls:
            enable_rls(bind, _TABLE)


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _TABLE):
        return
    if bind.dialect.name == "postgresql":
        op.execute(
            f"DROP POLICY IF EXISTS {_TABLE}_tenant_isolation ON {_TABLE}"
        )
    op.drop_index("ix_mcp_audit_log_created_at", table_name=_TABLE)
    op.drop_index("ix_mcp_audit_log_user_id", table_name=_TABLE)
    op.drop_table(_TABLE)
