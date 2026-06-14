"""add users.auto_execute_threshold_cents (Pillar 2B)

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-06-14

Adds the per-user bounded auto-execute threshold (integer cents, default 10000 =
$100, the market-canonical human-in-the-loop default). A rule whose per-firing
earmark is provably ≤ this fires unattended; above it the engine surfaces a
one-tap proposal instead. Virtual ``Goal.progress`` only — never gates real
money. Idempotent: a ``create_all``'d DB (tests/dev) already has the column, so
this just no-ops there.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d8e9f0a1b2c3"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, col: str) -> bool:
    return any(c["name"] == col for c in sa.inspect(bind).get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, "users", "auto_execute_threshold_cents"):
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "auto_execute_threshold_cents",
                    sa.Integer(),
                    nullable=False,
                    server_default="10000",
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "users", "auto_execute_threshold_cents"):
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_column("auto_execute_threshold_cents")
