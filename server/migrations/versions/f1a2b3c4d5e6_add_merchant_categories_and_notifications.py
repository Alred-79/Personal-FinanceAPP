"""add merchant_categories and notifications

Revision ID: f1a2b3c4d5e6
Revises: d5e6f7a8b9c0
Create Date: 2026-05-30

Adds the two tables introduced:

* ``merchant_categories`` — learned merchant → category mappings that make a
  user's renames / Groq results stick (one row per user+merchant).
* ``notifications`` — in-app nudges (budget overruns, anomalies) for the bell.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "merchant_categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("merchant", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, server_default="user"),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "merchant", name="uq_merchant_user_merchant"
        ),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("ref", sa.String(), nullable=True),
        sa.Column("read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notifications_ref", "notifications", ["ref"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_ref", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("merchant_categories")
