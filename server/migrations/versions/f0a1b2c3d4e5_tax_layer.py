"""tax & messy-data layer (Pillar 3)

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-06-14

Adds the four sidecar tables for the tax layer:

* ``tax_tags``            — a Schedule-C bucket on one transaction (orthogonal to
                            the spend category). ``(tx_type, tx_id)`` is NOT an
                            FK (overlapping expense/income id space, like
                            ``rule_executions``); a UNIQUE constraint gives one
                            tag per transaction. Orphan integrity is enforced in
                            code (delete hook + summary INNER join), not by an FK.
* ``merchant_tax_buckets``— learned merchant → bucket mapping (mirrors
                            ``merchant_categories``), unique per (user, merchant).
* ``tax_documents``       — a reviewed W-2/1099/1098 (confirm-then-write). Stores
                            money boxes + a last-4-only TIN; NEVER a full SSN/EIN,
                            and never the document bytes.
* ``mileage_logs``        — business miles (×1000 as an integer) → IRS-rate
                            deduction.

No Expense/Income column adds — the sidecar-table choice avoids rebuilding the
two hottest tables. Idempotent: a ``create_all``'d DB (the path tests use) already
has these tables, so each create no-ops there. Column types/defaults match the
ORM in ``db/models.py`` so this migration and ``Base.metadata.create_all`` agree.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f0a1b2c3d4e5"
down_revision = "e9f0a1b2c3d4"
branch_labels = None
depends_on = None


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table(bind, "tax_tags"):
        op.create_table(
            "tax_tags",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("tx_type", sa.String(), nullable=False),
            sa.Column("tx_id", sa.Integer(), nullable=False),
            sa.Column("tax_year", sa.Integer(), nullable=False),
            sa.Column("bucket", sa.String(), nullable=False),
            sa.Column(
                "business_personal",
                sa.String(),
                nullable=False,
                server_default="business",
            ),
            sa.Column(
                "deductible_bps", sa.Integer(), nullable=False, server_default="10000"
            ),
            sa.Column("source", sa.String(), nullable=False, server_default="user"),
            sa.Column("note", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.current_timestamp(),
                nullable=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.func.current_timestamp(),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tx_type", "tx_id", name="uq_tax_tag_tx"),
        )
        op.create_index(
            "ix_tax_tags_user_id", "tax_tags", ["user_id"], unique=False
        )

    if not _has_table(bind, "merchant_tax_buckets"):
        op.create_table(
            "merchant_tax_buckets",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("merchant", sa.String(), nullable=False),
            sa.Column("bucket", sa.String(), nullable=False),
            sa.Column("source", sa.String(), nullable=False, server_default="user"),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.func.current_timestamp(),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id", "merchant", name="uq_merchant_tax_user_merchant"
            ),
        )

    if not _has_table(bind, "tax_documents"):
        op.create_table(
            "tax_documents",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("tax_year", sa.Integer(), nullable=False),
            sa.Column("form_type", sa.String(), nullable=False),
            sa.Column(
                "issuer_name", sa.String(), nullable=False, server_default=""
            ),
            sa.Column("issuer_tin_last4", sa.String(), nullable=True),
            sa.Column(
                "fields_json", sa.String(), nullable=False, server_default="{}"
            ),
            sa.Column(
                "status",
                sa.String(),
                nullable=False,
                server_default="pending_review",
            ),
            sa.Column(
                "source_kind", sa.String(), nullable=False, server_default="image"
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.current_timestamp(),
                nullable=True,
            ),
            sa.Column("confirmed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_tax_documents_user_id", "tax_documents", ["user_id"], unique=False
        )

    if not _has_table(bind, "mileage_logs"):
        op.create_table(
            "mileage_logs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("trip_date", sa.String(), nullable=False),
            sa.Column("miles_milli", sa.Integer(), nullable=False),
            sa.Column("purpose", sa.String(), nullable=True),
            sa.Column(
                "business_personal",
                sa.String(),
                nullable=False,
                server_default="business",
            ),
            sa.Column("tax_year", sa.Integer(), nullable=False),
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
            "ix_mileage_logs_user_id", "mileage_logs", ["user_id"], unique=False
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "mileage_logs"):
        op.drop_index("ix_mileage_logs_user_id", table_name="mileage_logs")
        op.drop_table("mileage_logs")
    if _has_table(bind, "tax_documents"):
        op.drop_index("ix_tax_documents_user_id", table_name="tax_documents")
        op.drop_table("tax_documents")
    if _has_table(bind, "merchant_tax_buckets"):
        op.drop_table("merchant_tax_buckets")
    if _has_table(bind, "tax_tags"):
        op.drop_index("ix_tax_tags_user_id", table_name="tax_tags")
        op.drop_table("tax_tags")
