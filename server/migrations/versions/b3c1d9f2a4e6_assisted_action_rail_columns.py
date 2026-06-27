"""add rail origination columns to assisted_actions (Phase 2a–2b, SANDBOX ONLY)

Revision ID: b3c1d9f2a4e6
Revises: a7e920260619
Create Date: 2026-06-26

Adds the three nullable columns ``execute()`` needs to record a real-world money
movement originated at a rail: ``rail`` ("increase" | "method"), ``rail_ref`` (the
provider transfer/payment id), and ``settlement_detail_json`` (return R-codes /
failure reason / timestamps). A UNIQUE index on ``(rail, rail_ref)`` lets a
settlement webhook look the Bridge up by its provider id.

``settlement_status`` already exists (the assisted_actions baseline reserved it) —
do NOT re-add it. All new columns are nullable, so existing rows backfill as NULL
= "manual" with no data change. The whole path stays dark behind
``rail_origination_enabled`` (default False). Idempotent: a ``create_all``'d DB
(tests/dev) already has the columns/index, so this no-ops there.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b3c1d9f2a4e6"
down_revision = "a7e920260619"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, col: str) -> bool:
    return any(c["name"] == col for c in sa.inspect(bind).get_columns(table))


def _has_index(bind, table: str, name: str) -> bool:
    return any(ix["name"] == name for ix in sa.inspect(bind).get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("assisted_actions") as batch_op:
        if not _has_column(bind, "assisted_actions", "rail"):
            batch_op.add_column(sa.Column("rail", sa.String(), nullable=True))
        if not _has_column(bind, "assisted_actions", "rail_ref"):
            batch_op.add_column(sa.Column("rail_ref", sa.String(), nullable=True))
        if not _has_column(bind, "assisted_actions", "settlement_detail_json"):
            batch_op.add_column(
                sa.Column("settlement_detail_json", sa.String(), nullable=True)
            )
    if not _has_index(bind, "assisted_actions", "uq_assisted_actions_rail_ref"):
        op.create_index(
            "uq_assisted_actions_rail_ref",
            "assisted_actions",
            ["rail", "rail_ref"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_index(bind, "assisted_actions", "uq_assisted_actions_rail_ref"):
        op.drop_index(
            "uq_assisted_actions_rail_ref", table_name="assisted_actions"
        )
    with op.batch_alter_table("assisted_actions") as batch_op:
        if _has_column(bind, "assisted_actions", "settlement_detail_json"):
            batch_op.drop_column("settlement_detail_json")
        if _has_column(bind, "assisted_actions", "rail_ref"):
            batch_op.drop_column("rail_ref")
        if _has_column(bind, "assisted_actions", "rail"):
            batch_op.drop_column("rail")
