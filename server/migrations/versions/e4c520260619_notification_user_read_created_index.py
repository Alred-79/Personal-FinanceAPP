"""L4 — composite index on notifications(user_id, read, created_at)

Revision ID: e4c520260619
Revises: c2bb20260618
Create Date: 2026-06-19

The notifications feed reads per-user (filter user_id [+ read], order by
created_at) and the new retention sweep deletes old READ rows per user — both
benefit from a composite ``(user_id, read, created_at)`` index. Previously only
``ref`` was indexed. Idempotent: skipped when the table or index is absent/present.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e4c520260619"
down_revision = "c2bb20260618"
branch_labels = None
depends_on = None

_TABLE = "notifications"
_INDEX = "ix_notifications_user_read_created"


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def _has_index(bind, table: str, name: str) -> bool:
    return any(ix["name"] == name for ix in sa.inspect(bind).get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _TABLE) or _has_index(bind, _TABLE, _INDEX):
        return
    op.create_index(_INDEX, _TABLE, ["user_id", "read", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _TABLE) or not _has_index(bind, _TABLE, _INDEX):
        return
    op.drop_index(_INDEX, table_name=_TABLE)
