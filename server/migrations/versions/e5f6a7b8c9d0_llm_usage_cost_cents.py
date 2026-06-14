"""llm_usage.cost_cents — the real per-user daily dollar cap (A3)

Revision ID: e5f6a7b8c9d0
Revises: a1c2e3f4b5d6
Create Date: 2026-06-14 01:00:00.000000

Adds ``llm_usage.cost_cents`` so the LLM budget can enforce a per-user daily
DOLLAR ceiling, not just a request count. The chat stream reconciles this to the
actual cost (Groq usage_metadata when present, else a tiktoken count) priced at
``settings.groq_*_price_cents_per_mtok``. Defaults to 0 for existing rows.

The ``llm_usage`` table itself has no prior creating migration — it was added to
the ORM and only ever materialized via ``Base.metadata.create_all`` (app startup
/ tests). So this migration is self-sufficient: it CREATES the table (with
``cost_cents``) when absent, otherwise just ADDS the column. Idempotent either
way, so a create_all'd DB and a migrations-only DB converge to the same schema.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str]] = "a1c2e3f4b5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def _has_column(bind, table: str, col: str) -> bool:
    return any(c["name"] == col for c in sa.inspect(bind).get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "llm_usage"):
        # Materialize the whole meter table (it had no prior migration), already
        # carrying cost_cents. Mirrors the LlmUsage ORM model.
        op.create_table(
            "llm_usage",
            sa.Column("user_id", sa.Integer(), primary_key=True),
            sa.Column("day", sa.String(), primary_key=True),
            sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cost_cents", sa.Integer(), nullable=False, server_default="0"),
        )
        return
    if not _has_column(bind, "llm_usage", "cost_cents"):
        with op.batch_alter_table("llm_usage") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "cost_cents", sa.Integer(), nullable=False, server_default="0"
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "llm_usage") and _has_column(bind, "llm_usage", "cost_cents"):
        with op.batch_alter_table("llm_usage") as batch_op:
            batch_op.drop_column("cost_cents")
