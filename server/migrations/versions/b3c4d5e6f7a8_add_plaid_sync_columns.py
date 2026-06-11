"""add plaid sync columns

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-05-30 20:25:00.000000

Adds:
- tokens.cursor          — persists the Plaid /transactions/sync cursor
- expenses.plaid_transaction_id — Plaid-native dedup key
- income.plaid_transaction_id   — Plaid-native dedup key
- Composite unique indexes on (account_id, plaid_transaction_id)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, Sequence[str]] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add cursor to tokens and plaid_transaction_id to expenses/income."""
    # -- tokens --
    with op.batch_alter_table("tokens") as batch_op:
        batch_op.add_column(sa.Column("cursor", sa.String(), nullable=True))

    # -- expenses --
    with op.batch_alter_table("expenses") as batch_op:
        batch_op.add_column(
            sa.Column("plaid_transaction_id", sa.String(), nullable=True)
        )
        batch_op.create_index(
            "ix_expenses_acct_plaid_txn",
            ["account_id", "plaid_transaction_id"],
            unique=True,
        )

    # -- income --
    with op.batch_alter_table("income") as batch_op:
        batch_op.add_column(
            sa.Column("plaid_transaction_id", sa.String(), nullable=True)
        )
        batch_op.create_index(
            "ix_income_acct_plaid_txn",
            ["account_id", "plaid_transaction_id"],
            unique=True,
        )


def downgrade() -> None:
    """Remove plaid sync columns."""
    with op.batch_alter_table("income") as batch_op:
        batch_op.drop_index("ix_income_acct_plaid_txn")
        batch_op.drop_column("plaid_transaction_id")

    with op.batch_alter_table("expenses") as batch_op:
        batch_op.drop_index("ix_expenses_acct_plaid_txn")
        batch_op.drop_column("plaid_transaction_id")

    with op.batch_alter_table("tokens") as batch_op:
        batch_op.drop_column("cursor")
