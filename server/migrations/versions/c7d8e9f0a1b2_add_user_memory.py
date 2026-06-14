"""add user_memory

Revision ID: c7d8e9f0a1b2
Revises: e5f6a7b8c9d0
Create Date: 2026-06-14

Adds the ``user_memory`` table (Pillar 1A): durable learned facts/preferences
about the user that the assistant reads into its prompt every turn. Mixed-trust
``source`` ('user' | 'deterministic' | 'llm'); one row per (user, key).
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c7d8e9f0a1b2"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_memory",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, server_default="user"),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("pinned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "key", name="uq_user_memory_user_key"),
    )
    op.create_index(
        "ix_user_memory_user_id", "user_memory", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_user_memory_user_id", table_name="user_memory")
    op.drop_table("user_memory")
