"""plaid integrity (Step 08)

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-06-13 00:00:00.000000

Step 08 — Plaid integrity. Four changes, in a migration-footgun-safe order:

1. ``accounts.plaid_account_id`` — the Plaid account id this local account
   mirrors, so sync routes by id (not by shared name). Nullable; NULL = manual.
2. **De-duplicate** any existing rows that share a non-NULL
   ``plaid_transaction_id`` in ``expenses`` / ``income`` (the old
   check-then-insert could race and produce dupes) BEFORE creating the unique
   index, so the index build can't fail on current data. We keep the lowest
   ``id`` of each group.
3. **Partial UNIQUE index** on ``plaid_transaction_id`` for each table, with
   ``WHERE plaid_transaction_id IS NOT NULL`` so manual rows (NULL) are
   unaffected. A Plaid transaction id is globally unique per item, so the
   single-column partial index suffices.
4. **Encrypt** existing plaintext ``tokens.key`` values at rest (Fernet). The
   read path tolerates a legacy plaintext token, but this one-shot pass moves
   them to ciphertext (single-user: a handful of rows). An already-encrypted
   value (``enc:v1:`` prefix) is left untouched so the migration is idempotent.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str]] = "a0b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _dedupe(table: str) -> None:
    """Delete duplicate non-NULL plaid_transaction_id rows, keeping the min id."""
    op.execute(
        sa.text(
            f"""
            DELETE FROM {table}
            WHERE plaid_transaction_id IS NOT NULL
              AND id NOT IN (
                SELECT MIN(id) FROM {table}
                WHERE plaid_transaction_id IS NOT NULL
                GROUP BY plaid_transaction_id
              )
            """
        )
    )


def upgrade() -> None:
    # 1. accounts.plaid_account_id
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(
            sa.Column("plaid_account_id", sa.String(), nullable=True)
        )

    # 2. de-dupe BEFORE building the unique index (footgun-safe ordering)
    _dedupe("expenses")
    _dedupe("income")

    # 3. partial unique indexes (NULLs excluded → manual rows unaffected)
    op.create_index(
        "uq_expense_plaid_txn",
        "expenses",
        ["plaid_transaction_id"],
        unique=True,
        sqlite_where=sa.text("plaid_transaction_id IS NOT NULL"),
    )
    op.create_index(
        "uq_income_plaid_txn",
        "income",
        ["plaid_transaction_id"],
        unique=True,
        sqlite_where=sa.text("plaid_transaction_id IS NOT NULL"),
    )

    # 4. one-shot encrypt of existing plaintext Plaid access tokens.
    #    Imported lazily so the migration module imports without app settings on
    #    e.g. `alembic history`; only runs work when actually upgrading.
    from server.src.services import plaid_crypto

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, key FROM tokens")).fetchall()
    for row in rows:
        token_id, key = row[0], row[1]
        if key is None or plaid_crypto.is_encrypted(key):
            continue
        bind.execute(
            sa.text("UPDATE tokens SET key = :k WHERE id = :i"),
            {"k": plaid_crypto.encrypt(key), "i": token_id},
        )


def downgrade() -> None:
    op.drop_index("uq_income_plaid_txn", table_name="income")
    op.drop_index("uq_expense_plaid_txn", table_name="expenses")
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("plaid_account_id")
    # Tokens are left encrypted on downgrade: the read path tolerates ciphertext
    # only via plaid_crypto, so decrypting here would require the key be present;
    # the safe default is to leave them encrypted (a redo of upgrade is a no-op).
