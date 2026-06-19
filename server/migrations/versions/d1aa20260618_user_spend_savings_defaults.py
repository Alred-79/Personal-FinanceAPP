"""D1 — backfill + NOT NULL + server_default for users.spend_warning/savings_percent

Revision ID: d1aa20260618
Revises: f3b6c2d8e0a1
Create Date: 2026-06-18

The baseline schema created ``users.spend_warning`` and ``users.savings_percent``
as ``nullable=True`` with no default, but the ORM models them as NOT NULL
``Mapped[int]``. A row inserted on a migrated DB with NULL in either column would
fail Pydantic load against the NOT NULL model (a 500 on read). This migration
makes the DB match the model: backfill any NULLs to the model defaults FIRST,
then add the DEFAULT clause and the NOT NULL constraint.

Idempotent on a ``create_all``'d DB (tests/dev already have NOT NULL columns):
the backfill UPDATEs touch zero rows and the batch alter is a harmless no-op.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d1aa20260618"
down_revision = "f3b6c2d8e0a1"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, col: str) -> bool:
    return any(c["name"] == col for c in sa.inspect(bind).get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    if not (
        _has_column(bind, "users", "spend_warning")
        and _has_column(bind, "users", "savings_percent")
    ):
        return
    # Backfill NULLs BEFORE SET NOT NULL, or the ALTER fails on existing NULL rows.
    op.execute("UPDATE users SET spend_warning = 20 WHERE spend_warning IS NULL")
    op.execute(
        "UPDATE users SET savings_percent = 10 WHERE savings_percent IS NULL"
    )
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "spend_warning",
            existing_type=sa.Integer(),
            nullable=False,
            server_default="20",
        )
        batch_op.alter_column(
            "savings_percent",
            existing_type=sa.Integer(),
            nullable=False,
            server_default="10",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not (
        _has_column(bind, "users", "spend_warning")
        and _has_column(bind, "users", "savings_percent")
    ):
        return
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "spend_warning",
            existing_type=sa.Integer(),
            nullable=True,
            server_default=None,
        )
        batch_op.alter_column(
            "savings_percent",
            existing_type=sa.Integer(),
            nullable=True,
            server_default=None,
        )
