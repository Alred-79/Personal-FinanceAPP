"""messy-data ingestion: import sessions, rows, and import_row_id links

Revision ID: a1c2e3f4b5d6
Revises: d3e4f5a6b7c8
Create Date: 2026-06-14 00:00:01.000000

Adds the Reconciliation Desk / Import Anything storage:

* ``import_sessions`` — one messy-document import under review (statement-level
  balance facts + reconcile result). Raw bytes are never stored.
* ``import_rows`` — the parsed lines of a session, in signed whole cents.
* ``expenses.import_row_id`` / ``income.import_row_id`` — the non-Plaid dedup
  link from a committed transaction back to its source row, with a PARTIAL
  unique index (NULLs excluded) so manual and Plaid rows are unaffected and
  re-committing the same statement is idempotent.

SQLite can't ALTER ADD COLUMN-with-FK or ADD INDEX freely in place, so the
column additions use batch mode (table rebuild) like the rest of this schema.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1c2e3f4b5d6"
down_revision: Union[str, Sequence[str]] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. import_sessions — created before import_rows because rows FK to it.
    op.create_table(
        "import_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="pending_review"
        ),
        sa.Column("opening_balance", sa.Integer(), nullable=True),
        sa.Column("closing_balance", sa.Integer(), nullable=True),
        sa.Column("statement_period", sa.String(), nullable=True),
        sa.Column("reconciled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "discrepancy_cents", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column("committed_at", sa.DateTime(), nullable=True),
    )

    # 2. import_rows — the parsed lines.
    op.create_table(
        "import_rows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("import_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),  # signed cents
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False, server_default="Other"),
        sa.Column("merchant_key", sa.String(), nullable=False, server_default=""),
        sa.Column("running_balance", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="ok"),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("included", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("match_ref", sa.Integer(), nullable=True),
        sa.Column("committed_expense_id", sa.Integer(), nullable=True),
        sa.Column("committed_income_id", sa.Integer(), nullable=True),
    )

    # 3. expenses.import_row_id + partial unique index. Batch mode rebuilds the
    #    table; the partial index (NULLs excluded) mirrors the Plaid dedup index.
    #    SQLite batch mode requires the FK constraint to be NAMED.
    with op.batch_alter_table("expenses") as batch_op:
        batch_op.add_column(
            sa.Column(
                "import_row_id",
                sa.Integer(),
                sa.ForeignKey(
                    "import_rows.id",
                    ondelete="SET NULL",
                    name="fk_expense_import_row",
                ),
                nullable=True,
            )
        )
    op.create_index(
        "uq_expense_import_row",
        "expenses",
        ["import_row_id"],
        unique=True,
        sqlite_where=sa.text("import_row_id IS NOT NULL"),
    )

    # 4. income.import_row_id + partial unique index (mirrors expenses).
    with op.batch_alter_table("income") as batch_op:
        batch_op.add_column(
            sa.Column(
                "import_row_id",
                sa.Integer(),
                sa.ForeignKey(
                    "import_rows.id",
                    ondelete="SET NULL",
                    name="fk_income_import_row",
                ),
                nullable=True,
            )
        )
    op.create_index(
        "uq_income_import_row",
        "income",
        ["import_row_id"],
        unique=True,
        sqlite_where=sa.text("import_row_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_income_import_row", table_name="income")
    with op.batch_alter_table("income") as batch_op:
        batch_op.drop_column("import_row_id")

    op.drop_index("uq_expense_import_row", table_name="expenses")
    with op.batch_alter_table("expenses") as batch_op:
        batch_op.drop_column("import_row_id")

    op.drop_table("import_rows")
    op.drop_table("import_sessions")
