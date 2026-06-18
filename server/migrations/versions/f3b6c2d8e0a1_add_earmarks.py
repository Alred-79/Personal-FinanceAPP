"""add earmarks (W7 F4 — soft goal sub-buckets)

Revision ID: f3b6c2d8e0a1
Revises: e2a9c4d7f1b8
Create Date: 2026-06-18 00:00:00.000000

Adds:
- earmarks — a soft, named sub-bucket of a goal's earmarked savings. ``Goal.progress``
  already is a virtual earmark that reduces Safe-to-Spend; an ``earmark`` partitions
  that single bucket into named sub-buckets (Soman & Cheema mental accounting). It is
  SOFT: setting an earmark adds its cents to ``Goal.progress``; pulling it back subtracts
  the same cents — always allowed, instant, no penalty. ``user_id`` is denormalized
  (== the goal's owner) so RLS filters it directly (WS2). One named bucket per goal.

When the deployment has opted into RLS (``settings.enable_rls`` AND Postgres), the
tenant-isolation policy is installed on the new table too, keeping it consistent with
the rest of TENANT_TABLES. A no-op on SQLite / with RLS off.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f3b6c2d8e0a1"
down_revision: Union[str, Sequence[str]] = "e2a9c4d7f1b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "earmarks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "goal_id",
            sa.Integer(),
            sa.ForeignKey("goals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint("goal_id", "name", name="uq_earmark_goal_name"),
    )
    op.create_index("ix_earmarks_goal_id", "earmarks", ["goal_id"])
    op.create_index("ix_earmarks_user_id", "earmarks", ["user_id"])

    # Install the tenant-isolation policy when the deployment has opted into RLS
    # (mirrors the enable_rls migration + the create_all listener; same helper/list).
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        from server.src.db.rls import enable_rls
        from server.src.settings import settings

        if settings.enable_rls:
            enable_rls(bind, "earmarks")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS earmarks_tenant_isolation ON earmarks")
    op.drop_index("ix_earmarks_user_id", table_name="earmarks")
    op.drop_index("ix_earmarks_goal_id", table_name="earmarks")
    op.drop_table("earmarks")
