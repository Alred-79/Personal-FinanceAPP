"""account name uniqueness per user

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-06-14 00:00:00.000000

Add a UNIQUE(user_id, name) constraint on ``accounts``. Two accounts with the
same name under one user break the legacy name-based matching still used for
pre-Step-08 (manually managed) accounts and confuse the account picker.

Footgun-safe ordering: any pre-existing duplicate (user_id, name) rows are
disambiguated FIRST — by suffixing the later rows " (2)", " (3)", … keyed by id
— so the constraint build can't fail on current data. Renaming (not deleting)
is deliberate: an account owns transactions via cascade, so deleting a
duplicate would destroy financial history.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, Sequence[str]] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _disambiguate_duplicate_names() -> None:
    """Suffix later duplicate (user_id, name) rows so the unique build succeeds.

    For each group sharing (user_id, name), the lowest-id row keeps the original
    name; the rest get " (2)", " (3)", … in id order. If a suffixed name would
    itself collide, the loop keeps incrementing until it is free.
    """
    bind = op.get_bind()
    dupes = bind.execute(
        sa.text(
            """
            SELECT user_id, name
            FROM accounts
            GROUP BY user_id, name
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()

    for user_id, name in dupes:
        # All rows in this group, oldest first; skip the first (keeps the name).
        rows = bind.execute(
            sa.text(
                "SELECT id FROM accounts "
                "WHERE user_id = :u AND name = :n ORDER BY id"
            ),
            {"u": user_id, "n": name},
        ).fetchall()
        for offset, (acct_id,) in enumerate(rows[1:], start=2):
            candidate = f"{name} ({offset})"
            bump = offset
            # Ensure the new name is free for this user.
            while bind.execute(
                sa.text(
                    "SELECT 1 FROM accounts "
                    "WHERE user_id = :u AND name = :n LIMIT 1"
                ),
                {"u": user_id, "n": candidate},
            ).first():
                bump += 1
                candidate = f"{name} ({bump})"
            bind.execute(
                sa.text("UPDATE accounts SET name = :n WHERE id = :i"),
                {"n": candidate, "i": acct_id},
            )


def upgrade() -> None:
    # 1. de-dupe BEFORE adding the constraint (footgun-safe ordering)
    _disambiguate_duplicate_names()

    # 2. add the unique constraint. SQLite can't ALTER ADD CONSTRAINT in place,
    #    so use batch mode (table-rebuild) like the rest of this schema.
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.create_unique_constraint(
            "uq_account_user_name", ["user_id", "name"]
        )


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_constraint("uq_account_user_name", type_="unique")
