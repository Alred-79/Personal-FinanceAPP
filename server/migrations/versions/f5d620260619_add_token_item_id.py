"""L1 — add tokens.item_id (Plaid webhook routing)

Revision ID: f5d620260619
Revises: e4c520260619
Create Date: 2026-06-19

Inbound Plaid webhooks are keyed by ``item_id``; persisting it on the Token row is
how a webhook routes to the right token/user server-side. Nullable + non-unique
index. NO backfill — item_id isn't derivable offline (the access token is
encrypted), so pre-existing items get it on the next re-link. Idempotent.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f5d620260619"
down_revision = "e4c520260619"
branch_labels = None
depends_on = None

_TABLE = "tokens"
_COL = "item_id"
_INDEX = "ix_tokens_item_id"


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def _has_column(bind, table: str, col: str) -> bool:
    return any(c["name"] == col for c in sa.inspect(bind).get_columns(table))


def _has_index(bind, table: str, name: str) -> bool:
    return any(ix["name"] == name for ix in sa.inspect(bind).get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _TABLE):
        return
    with op.batch_alter_table(_TABLE) as batch_op:
        if not _has_column(bind, _TABLE, _COL):
            batch_op.add_column(sa.Column(_COL, sa.String(), nullable=True))
    if not _has_index(bind, _TABLE, _INDEX):
        op.create_index(_INDEX, _TABLE, [_COL])


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, _TABLE):
        return
    if _has_index(bind, _TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
    if _has_column(bind, _TABLE, _COL):
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.drop_column(_COL)
