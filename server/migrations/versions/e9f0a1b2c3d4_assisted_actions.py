"""add assisted_actions (Pillar 2C — the Assisted Action Bridge)

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-06-14

Adds the ``assisted_actions`` table: a deduced real-world action the agent hands
the user a one-tap path to execute, reconciled against the next Plaid sync.

Two status columns from day one ON PURPOSE: ``status`` (human-action lifecycle)
and a nullable ``settlement_status`` (reserved for a future originated-transfer
state machine; stays NULL until origination is ever built) — so a graduation to
real money needs no live-row status migration. Idempotent: a ``create_all``'d DB
already has the table, so this no-ops there.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e9f0a1b2c3d4"
down_revision = "d8e9f0a1b2c3"
branch_labels = None
depends_on = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "assisted_actions"):
        return
    op.create_table(
        "assisted_actions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column("dest_ref", sa.String(), nullable=True),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("how_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(), nullable=False, server_default="proposed"),
        # Reserved for the real-money appendix; NULL until origination exists.
        sa.Column("settlement_status", sa.String(), nullable=True),
        sa.Column("verify_ref", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=True),
        sa.Column("resolved_at", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assisted_actions_user_id", "assisted_actions", ["user_id"], unique=False
    )
    op.create_index(
        "ix_assisted_actions_verify_ref",
        "assisted_actions",
        ["verify_ref"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "assisted_actions"):
        return
    op.drop_index("ix_assisted_actions_verify_ref", table_name="assisted_actions")
    op.drop_index("ix_assisted_actions_user_id", table_name="assisted_actions")
    op.drop_table("assisted_actions")
