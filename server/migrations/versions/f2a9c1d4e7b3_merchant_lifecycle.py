"""merchant lifecycle snapshot (F2)

Revision ID: f2a9c1d4e7b3
Revises: f0a1b2c3d4e5
Create Date: 2026-06-18

Adds the ``merchant_lifecycle`` sidecar table: a snapshot of the pooled BG/NBD
lifecycle model's per-merchant output (probability_alive, expected_purchases,
status) plus the deterministic price-creep comparison (last vs prev amount).
Refreshed by F3's nightly job; reads never fit inline. One row per
``(user, merchant)``.

Idempotent: a ``create_all``'d DB (the path tests use) already has the table, so
the create no-ops there. Column types/defaults match the ORM in ``db/models.py``
so this migration and ``Base.metadata.create_all`` agree.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f2a9c1d4e7b3"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table(bind, "merchant_lifecycle"):
        op.create_table(
            "merchant_lifecycle",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("merchant", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False, server_default=""),
            sa.Column(
                "probability_alive", sa.Float(), nullable=False, server_default="1.0"
            ),
            sa.Column(
                "expected_purchases", sa.Float(), nullable=False, server_default="0.0"
            ),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("cadence", sa.String(), nullable=True),
            sa.Column("n_charges", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_amount", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("prev_amount", sa.Integer(), nullable=True),
            sa.Column("price_change_pct", sa.Float(), nullable=True),
            sa.Column("last_date", sa.String(), nullable=True),
            sa.Column("expected_next_date", sa.String(), nullable=True),
            sa.Column("fitted_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id", "merchant", name="uq_merchant_lifecycle_user_merchant"
            ),
        )
        op.create_index(
            "ix_merchant_lifecycle_user_id",
            "merchant_lifecycle",
            ["user_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "merchant_lifecycle"):
        op.drop_index("ix_merchant_lifecycle_user_id", table_name="merchant_lifecycle")
        op.drop_table("merchant_lifecycle")
