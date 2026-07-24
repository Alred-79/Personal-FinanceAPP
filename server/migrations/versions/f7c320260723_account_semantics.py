"""normalize account balance semantics

Revision ID: f7c320260723
Revises: e5b220260723
Create Date: 2026-07-23

Preserves the legacy ``balance`` column while adding the raw fields required to
distinguish liquid cash, assets, liabilities, currencies, and balance freshness.
Existing manual accounts receive an explicit USD assumption; linked accounts
must refresh before their missing Plaid currency/available fields are trusted.
"""

from alembic import op
import sqlalchemy as sa


revision = "f7c320260723"
down_revision = "e5b220260723"
branch_labels = None
depends_on = None


_COLUMNS = (
    sa.Column("subtype", sa.String(), nullable=True),
    sa.Column("current_balance", sa.Integer(), nullable=True),
    sa.Column("available_balance", sa.Integer(), nullable=True),
    sa.Column("credit_limit", sa.Integer(), nullable=True),
    sa.Column("iso_currency_code", sa.String(length=3), nullable=True),
    sa.Column("unofficial_currency_code", sa.String(), nullable=True),
    sa.Column("balance_source", sa.String(), nullable=True),
    sa.Column("balance_observed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("semantic_role", sa.String(), nullable=True),
    sa.Column(
        "review_state",
        sa.String(),
        nullable=False,
        server_default="legacy_unverified",
    ),
)


def _has_column(bind, table: str, name: str) -> bool:
    return any(col["name"] == name for col in sa.inspect(bind).get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    for column in _COLUMNS:
        if not _has_column(bind, "accounts", column.name):
            op.add_column("accounts", column)

    op.execute(
        sa.text(
            """
            UPDATE accounts
            SET current_balance = balance,
                balance_source = CASE
                    WHEN plaid_account_id IS NULL THEN 'manual'
                    ELSE 'plaid'
                END,
                balance_observed_at = COALESCE(plaid_balance_refreshed_at, last_updated),
                iso_currency_code = CASE
                    WHEN plaid_account_id IS NULL THEN 'USD'
                    ELSE iso_currency_code
                END,
                semantic_role = CASE lower(type)
                    WHEN 'checking' THEN 'liquid_asset'
                    WHEN 'savings' THEN 'liquid_asset'
                    WHEN 'spending' THEN 'liquid_asset'
                    WHEN 'cash' THEN 'liquid_asset'
                    WHEN 'depository' THEN 'liquid_asset'
                    WHEN 'investment' THEN 'nonliquid_asset'
                    WHEN 'brokerage' THEN 'nonliquid_asset'
                    WHEN 'credit' THEN 'liability'
                    WHEN 'credit card' THEN 'liability'
                    WHEN 'loan' THEN 'liability'
                    WHEN 'mortgage' THEN 'liability'
                    WHEN 'liability' THEN 'liability'
                    ELSE 'unknown'
                END,
                review_state = CASE lower(type)
                    WHEN 'checking' THEN 'inferred'
                    WHEN 'savings' THEN 'inferred'
                    WHEN 'spending' THEN 'inferred'
                    WHEN 'cash' THEN 'inferred'
                    WHEN 'depository' THEN 'inferred'
                    WHEN 'investment' THEN 'inferred'
                    WHEN 'brokerage' THEN 'inferred'
                    WHEN 'credit' THEN 'inferred'
                    WHEN 'credit card' THEN 'inferred'
                    WHEN 'loan' THEN 'inferred'
                    WHEN 'mortgage' THEN 'inferred'
                    WHEN 'liability' THEN 'inferred'
                    ELSE 'review_required'
                END
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    for column in reversed(_COLUMNS):
        if _has_column(bind, "accounts", column.name):
            op.drop_column("accounts", column.name)
