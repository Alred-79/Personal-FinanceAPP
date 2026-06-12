"""canon_facts (v4 package 07 — the Chronicler)

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-06-12

Adds the ``canon_facts`` table — durable saga facts written only by engine event
subscriptions (the LLM never writes canon). Additive only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str]] = "c6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canon_facts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("source_event_id", sa.Integer(), nullable=True),
        sa.UniqueConstraint("user_id", "key", name="uq_canon_user_key"),
    )
    op.create_index("ix_canon_facts_user_id", "canon_facts", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_canon_facts_user_id", table_name="canon_facts")
    op.drop_table("canon_facts")
