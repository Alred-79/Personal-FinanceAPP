"""add used_action_tokens

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-05-31

Adds the ``used_action_tokens`` table that backs the single-use guard for
assistant write-action confirmation tokens. The UNIQUE constraint on ``jti``
makes "confirm at most once" durable and correct across multiple workers/hosts
(an in-process cache would only cover a single worker).
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "used_action_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("jti", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_used_action_tokens_jti",
        "used_action_tokens",
        ["jti"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_used_action_tokens_jti", table_name="used_action_tokens"
    )
    op.drop_table("used_action_tokens")
