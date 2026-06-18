"""runs — the Expedition snapshot (v4 package 08)

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-06-12

Adds the ``runs`` table. ``map_json`` is the immutable draft snapshot — a DB
trigger rejects any UPDATE that changes it (world stability: forecast drift never
moves nodes; mid-run changes go to overlay_json). Additive only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, Sequence[str]] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MAP_IMMUTABLE_TRIGGER = (
    "CREATE TRIGGER IF NOT EXISTS runs_map_json_immutable "
    "BEFORE UPDATE OF map_json ON runs "
    "FOR EACH ROW WHEN OLD.map_json IS NOT NULL AND NEW.map_json <> OLD.map_json "
    "BEGIN SELECT RAISE(ABORT, 'runs.map_json is an immutable draft snapshot'); END"
)


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("month", sa.String(), nullable=False),
        sa.Column("map_json", sa.String(), nullable=False),
        sa.Column("overlay_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("modifier_key", sa.String(), nullable=True),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("sealed_at", sa.String(), nullable=True),
        sa.Column("score_json", sa.String(), nullable=True),
        sa.UniqueConstraint("user_id", "month", name="uq_run_user_month"),
    )
    op.create_index("ix_runs_user_id", "runs", ["user_id"])
    # Dialect-branched immutability trigger (see server/src/db/models.py). SQLite's
    # RAISE(ABORT, ...) is not valid Postgres, so PG gets a PL/pgSQL function.
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE OR REPLACE FUNCTION runs_map_json_immutable_fn() RETURNS trigger "
            "AS $$ BEGIN IF OLD.map_json IS NOT NULL AND NEW.map_json <> OLD.map_json "
            "THEN RAISE EXCEPTION 'runs.map_json is an immutable draft snapshot'; "
            "END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER runs_map_json_immutable BEFORE UPDATE OF map_json ON runs "
            "FOR EACH ROW EXECUTE FUNCTION runs_map_json_immutable_fn()"
        )
    else:
        op.execute(_MAP_IMMUTABLE_TRIGGER)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS runs_map_json_immutable ON runs")
        op.execute("DROP FUNCTION IF EXISTS runs_map_json_immutable_fn()")
    else:
        op.execute("DROP TRIGGER IF EXISTS runs_map_json_immutable")
    op.drop_index("ix_runs_user_id", table_name="runs")
    op.drop_table("runs")
