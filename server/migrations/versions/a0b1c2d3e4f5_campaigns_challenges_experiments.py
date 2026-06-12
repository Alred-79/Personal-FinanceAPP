"""campaigns, challenges, experiments (v4 package 10)

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-06-12

Adds the package-10 tables:

* ``campaigns`` + ``campaign_progress`` — the quarterly arc. A campaign NEVER
  expires (there is no 'expired' status anywhere); an unfinished track pauses at
  quarter end and resumes on next activity. Milestone grants are derived from
  the event log, so retroactive catch-up is free.
* ``challenges`` — challenge INSTANCES (the registry of kinds lives in code).
* ``experiment_exposures`` + ``metric_rollups`` — OBSERVABILITY tables. Exposure
  and metrics logging never lands in ``game_events`` (the event log is domain
  history, not analytics).
* ``metric_fade`` — per-metric graduation/fade state + the user pin.
* ``users.experiment_cohort`` — assigned at first game activation; stable hash
  bucket. Holdout users keep the full Money Spine (never withheld).

Additive only. Kill switches are config (settings), NOT schema — killing a
feature must never require a migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, Sequence[str]] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("quarter", sa.String(), nullable=False),  # e.g. '2026-Q2'
        sa.Column("arc_key", sa.String(), nullable=False),
        # 'active' | 'paused' | 'complete' — there is deliberately NO 'expired'.
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.UniqueConstraint("user_id", "quarter", name="uq_campaigns_user_quarter"),
    )
    op.create_index("ix_campaigns_user_id", "campaigns", ["user_id"])

    op.create_table(
        "campaign_progress",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "campaign_id",
            sa.Integer(),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("milestone_key", sa.String(), nullable=False),
        sa.Column("granted_at", sa.String(), nullable=False),
        sa.Column(
            "source_event_id",
            sa.Integer(),
            sa.ForeignKey("game_events.id"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "campaign_id", "milestone_key", name="uq_campaign_progress_milestone"
        ),
    )

    op.create_table(
        "challenges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),  # 1 | 2 | 3
        sa.Column("category", sa.String(), nullable=False, server_default=""),
        # 'active' | 'met' | 'void' | 'soft_landed' — never below baseline, no
        # stake, no 'failed-with-loss' state exists by construction.
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("starts_on", sa.String(), nullable=False),
        sa.Column("ends_on", sa.String(), nullable=False),
        sa.Column("params_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("verdict_json", sa.String(), nullable=True),
        sa.Column("cosmetic_credit", sa.Integer(), nullable=False, server_default="0"),
        # Declined graduation offers are suppressed until this date (30 days).
        sa.Column("suppressed_until", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.current_timestamp()
        ),
    )
    op.create_index("ix_challenges_user_id", "challenges", ["user_id"])

    # Observability — NOT game state. Never folded, never rebuilt, never XP.
    op.create_table(
        "experiment_exposures",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("flag", sa.String(), nullable=False),
        sa.Column("arm", sa.String(), nullable=False),
        sa.Column("surface", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index(
        "ix_experiment_exposures_user_id", "experiment_exposures", ["user_id"]
    )

    op.create_table(
        "metric_rollups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("week", sa.String(), nullable=False),  # ISO Monday
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cohort", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint(
            "user_id", "week", "metric", name="uq_metric_rollups_user_week_metric"
        ),
    )

    op.create_table(
        "metric_fade",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric", sa.String(), nullable=False),  # category name
        # 'active' | 'graduated' — fade quiets the GAME layer for a metric; it
        # NEVER touches Money Spine alerts, the glanceable number, or Grace.
        sa.Column("state", sa.String(), nullable=False, server_default="active"),
        sa.Column("stable_weeks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("regressed_weeks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("graduated_on", sa.String(), nullable=True),
        # 'none' | 'always_active' | 'always_faded' — user autonomy, both ways.
        sa.Column("pin", sa.String(), nullable=False, server_default="none"),
        sa.UniqueConstraint("user_id", "metric", name="uq_metric_fade_user_metric"),
    )

    # Holdout cohort: assigned once at first game activation, stable thereafter.
    op.add_column(
        "users", sa.Column("experiment_cohort", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "experiment_cohort")
    op.drop_table("metric_fade")
    op.drop_table("metric_rollups")
    op.drop_index(
        "ix_experiment_exposures_user_id", table_name="experiment_exposures"
    )
    op.drop_table("experiment_exposures")
    op.drop_index("ix_challenges_user_id", table_name="challenges")
    op.drop_table("challenges")
    op.drop_table("campaign_progress")
    op.drop_index("ix_campaigns_user_id", table_name="campaigns")
    op.drop_table("campaigns")
