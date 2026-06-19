"""C2 — tax_tags uniqueness becomes per-user (uq_tax_tag_user_tx)

Revision ID: c2bb20260618
Revises: d1aa20260618
Create Date: 2026-06-18

The old ``UniqueConstraint("tx_type", "tx_id")`` treated a transaction id as
globally unique, but expenses/income id spaces overlap across users, so two
users tagging "expense #5" collided (and the tag upsert silently reassigned
ownership — a latent IDOR). This widens the constraint to
``("user_id", "tx_type", "tx_id")`` so one tag per transaction PER USER.

SQLite can't ALTER a constraint in place, so we recreate the table via
``batch_alter_table`` (drop the old named constraint, add the new one). Before
adding the new constraint we assert no pre-existing rows violate it (today tx_id
is globally unique per table, so duplicates shouldn't exist). Idempotent: skipped
when the table is absent.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c2bb20260618"
down_revision = "d1aa20260618"
branch_labels = None
depends_on = None

_OLD = "uq_tax_tag_tx"
_NEW = "uq_tax_tag_user_tx"


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def _assert_no_violation(bind, cols: tuple[str, ...]) -> None:
    """Fail loudly if existing rows would violate the about-to-be-added unique
    constraint, rather than letting the table recreate raise opaquely."""
    group = ", ".join(cols)
    dupes = bind.execute(
        sa.text(
            f"SELECT COUNT(*) FROM (SELECT {group} FROM tax_tags "
            f"GROUP BY {group} HAVING COUNT(*) > 1)"
        )
    ).scalar()
    if dupes:
        raise RuntimeError(
            f"tax_tags has {dupes} group(s) violating uniqueness on ({group}); "
            "resolve duplicates before applying c2bb20260618."
        )


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "tax_tags"):
        return
    _assert_no_violation(bind, ("user_id", "tx_type", "tx_id"))
    with op.batch_alter_table(
        "tax_tags",
        naming_convention={"uq": "%(table_name)s_%(column_0_name)s_key"},
    ) as batch_op:
        batch_op.drop_constraint(_OLD, type_="unique")
        batch_op.create_unique_constraint(_NEW, ["user_id", "tx_type", "tx_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "tax_tags"):
        return
    _assert_no_violation(bind, ("tx_type", "tx_id"))
    with op.batch_alter_table(
        "tax_tags",
        naming_convention={"uq": "%(table_name)s_%(column_0_name)s_key"},
    ) as batch_op:
        batch_op.drop_constraint(_NEW, type_="unique")
        batch_op.create_unique_constraint(_OLD, ["tx_type", "tx_id"])
