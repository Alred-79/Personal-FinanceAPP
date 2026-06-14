"""scenarios and plan_of_record (v6 doc 03)

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-06-13

Two tables backing saved/named/comparable scenarios (v6):

- ``scenarios``        — a named, owned ``ScenarioOverlay``. The overlay lives in
                         ``overlay_json`` as a schema-versioned dict whose every
                         money field is integer cents — there are deliberately NO
                         top-level money columns here, so the cents discipline is
                         enforced inside the JSON, never split across columns.
- ``plans_of_record``  — a committed plan: the rule ids that make it up plus a
                         baseline snapshot to drift-check against later (doc 06).
                         ``scenario_id`` is SET NULL on the scenario's deletion so
                         committing a plan does not pin its source scenario.

Timestamps default to ``CURRENT_TIMESTAMP``; FKs carry explicit ``ondelete``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, Sequence[str]] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scenarios",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("overlay_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_scenarios_user", "scenarios", ["user_id"])

    op.create_table(
        "plans_of_record",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scenario_id",
            sa.Integer(),
            sa.ForeignKey("scenarios.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rule_ids_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("baseline_snapshot_json", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column(
            "committed_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_plans_of_record_user", "plans_of_record", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_plans_of_record_user", table_name="plans_of_record")
    op.drop_table("plans_of_record")
    op.drop_index("ix_scenarios_user", table_name="scenarios")
    op.drop_table("scenarios")
