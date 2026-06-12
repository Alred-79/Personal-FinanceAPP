"""rules engine tables (v1 Layer B)

Revision ID: e4f5a6b7c8d9
Revises: d2e3f4a5b6c7
Create Date: 2026-06-11

- rules            — user automation rules. The target is generic on purpose
                     (target_kind + target_id, not target_goal_id) so v4 can add
                     target_kind='liability' with no migration.
- rule_executions  — idempotency log; unique (rule_id, tx_type, tx_id) keeps
                     re-imports/re-syncs from double-firing. Stores action_type
                     + amount_cents + fired_at so it doubles as the v4
                     automated-save event source.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, Sequence[str]] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("conditions", sa.String(), nullable=False, server_default="[]"),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("action_params", sa.String(), nullable=False, server_default="{}"),
        sa.Column("target_kind", sa.String(), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_rules_user", "rules", ["user_id"])

    op.create_table(
        "rule_executions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "rule_id",
            sa.Integer(),
            sa.ForeignKey("rules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tx_type", sa.String(), nullable=False),
        sa.Column("tx_id", sa.Integer(), nullable=False),
        sa.Column(
            "fired_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result", sa.String(), nullable=False, server_default="ok"),
        sa.UniqueConstraint("rule_id", "tx_type", "tx_id", name="uq_rule_exec_tx"),
    )


def downgrade() -> None:
    op.drop_table("rule_executions")
    op.drop_index("ix_rules_user", table_name="rules")
    op.drop_table("rules")
