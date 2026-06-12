"""Campaigns — the quarterly arc over expeditions (v4 §7.3, §9.4).

The long arc (ranks, lore) feeds off prestige + the bestiary; it adds NO new
mechanics. Three structural laws, each test-enforced:

* **Non-expiry.** An unfinished track PAUSES at quarter end and resumes on the
  next activity. Milestones remain claimable forever. There is no countdown
  anywhere in a campaign surface, and no expiry status exists for any code
  path to set (the status enum is active/paused/complete, nothing else).
* **Real-event milestones.** Every milestone derives from an XP-bearing or
  structural event (GREEN weeks, boss phases, sealed months) — never from
  logins/opens/views. A registry test walks ``MILESTONES`` and asserts it.
* **Retroactive catch-up.** Grants are COMPUTED from the event log, so a user
  who joins or lapses mid-quarter is auto-granted every milestone the log
  already supports. The log makes this free.

Rank ascension: a display rank (E→S) from the lifetime prestige curve —
monotonic and sub-linear, and prestige only ever accrues, so the rank can
never decrease.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...db.models import Campaign, CampaignProgress, GameEvent
from ...models import UserInDB
from .events import GameEventDraft, record_events, register_event_type

for _t in ("CampaignMilestoneGranted", "CampaignPaused", "CampaignResumed"):
    register_event_type(_t, 1)


# ── the milestone registry ──────────────────────────────────────────────────

# Structural (non-XP-bearing) event types a milestone may legitimately derive
# from: sealed months, boss phases/defeats, prestige. The registry test asserts
# every milestone source is XP-bearing OR in this set — and engagement-shaped
# types (logins/opens/views) can never appear.
STRUCTURAL_SOURCES: set[str] = {
    "MonthSealed",
    "BossPhaseBroken",
    "BossDefeated",
    "PrestigeMinted",
}


@dataclass(frozen=True)
class CampaignMilestone:
    key: str
    label_term: str  # term-catalog key — copy never hardcoded here
    source_event: str  # the event type whose count drives the grant
    threshold: int  # grant when count(source_event) >= threshold


# Trough-plan scheduling (v4 §9.4): novelty-curve studies show the engagement
# trough for habit products lands in weeks 4-8 of a new user's life, after the
# onboarding spike fades and before the habit is self-sustaining. The first
# three thresholds below are deliberately sized so that a typically-engaged new
# user crosses them in that window: ~5 green days accumulate by week 4-5, the
# first boss phase breaks with the first 1-2 debt payments (weeks 4-8 for a
# monthly payer), and the first sealed month arrives at the week-5 boundary.
# Content lands when motivation dips — not in week 1, when it isn't needed.
MILESTONES: tuple[CampaignMilestone, ...] = (
    CampaignMilestone(
        key="green_week_1",
        label_term="campaign.milestone.green_week_1",
        source_event="UnderBudgetDayClosed",
        threshold=5,
    ),
    CampaignMilestone(
        key="boss_phase_1",
        label_term="campaign.milestone.boss_phase_1",
        source_event="BossPhaseBroken",
        threshold=1,
    ),
    CampaignMilestone(
        key="month_sealed_1",
        label_term="campaign.milestone.month_sealed_1",
        source_event="MonthSealed",
        threshold=1,
    ),
    CampaignMilestone(
        key="green_week_4",
        label_term="campaign.milestone.green_week_4",
        source_event="UnderBudgetDayClosed",
        threshold=20,
    ),
    CampaignMilestone(
        key="month_sealed_2",
        label_term="campaign.milestone.month_sealed_2",
        source_event="MonthSealed",
        threshold=2,
    ),
    CampaignMilestone(
        key="bestiary_first_seal",
        label_term="campaign.milestone.bestiary_first_seal",
        source_event="BossDefeated",
        threshold=1,
    ),
    CampaignMilestone(
        key="month_sealed_3",
        label_term="campaign.milestone.month_sealed_3",
        source_event="MonthSealed",
        threshold=3,
    ),
)

# Themed arcs cycle by quarter index; theming is template hooks for the
# Chronicler (LLM flavor flows through 07's validated pipeline, never here).
ARCS: tuple[str, ...] = ("the_long_thaw", "the_high_road", "the_quiet_harvest",
                         "the_iron_season")


# ── rank ascension (display only) ───────────────────────────────────────────

# Lifetime-prestige thresholds for each display rank. Sub-linear: each step
# costs more than the last. Prestige only accrues (PrestigeMinted is additive,
# never negative), so the rank is monotonic over a user's life by construction.
RANK_THRESHOLDS: tuple[tuple[int, str], ...] = (
    (0, "E"),
    (3, "D"),
    (8, "C"),
    (16, "B"),
    (30, "A"),
    (52, "S"),
)


def rank_for_prestige(lifetime_prestige: int) -> str:
    """Display rank from lifetime prestige. Monotonic, sub-linear, never
    decreases (prestige never decreases)."""
    rank = "E"
    for floor, label in RANK_THRESHOLDS:
        if lifetime_prestige >= floor:
            rank = label
    return rank


def lifetime_prestige(db: Session) -> int:
    """Sum of all PrestigeMinted payloads — accrual only, never spent down."""
    import json

    rows = db.execute(
        select(GameEvent.payload).where(GameEvent.type == "PrestigeMinted")
    ).scalars().all()
    return sum(int(json.loads(p).get("prestige", 0)) for p in rows)


# ── quarter helpers ─────────────────────────────────────────────────────────


def quarter_of(d: date) -> str:
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def _arc_for_quarter(quarter: str) -> str:
    year, q = quarter.split("-Q")
    idx = (int(year) * 4 + int(q) - 1) % len(ARCS)
    return ARCS[idx]


# ── the service ─────────────────────────────────────────────────────────────


class CampaignService:
    """Owns ``campaigns`` + ``campaign_progress``. Grants derive from the event
    log; this service never writes financial truth."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── lifecycle: ensure / pause / resume (never expire) ──────────────────

    def ensure(self, user: UserInDB, as_of: date) -> Campaign:
        """The user's campaign for *as_of*'s quarter — resuming a paused track
        from an earlier quarter first (non-expiry: the SAME track continues),
        else creating a fresh arc for this quarter."""
        quarter = quarter_of(as_of)
        current = self._get(user.id, quarter)
        if current is not None:
            if current.status == "paused":
                self._resume(user, current, as_of)
            return current
        # An unfinished earlier track resumes instead of a new one starting.
        unfinished = self.db.execute(
            select(Campaign).where(
                Campaign.user_id == user.id,
                Campaign.status.in_(("active", "paused")),
            ).order_by(Campaign.quarter.desc())
        ).scalars().first()
        if unfinished is not None:
            if unfinished.status == "paused":
                self._resume(user, unfinished, as_of)
            return unfinished
        campaign = Campaign(
            user_id=user.id, quarter=quarter, arc_key=_arc_for_quarter(quarter),
            status="active", started_at=as_of.isoformat(),
        )
        self.db.add(campaign)
        self.db.flush()
        return campaign

    def _get(self, user_id: int, quarter: str) -> Optional[Campaign]:
        return self.db.execute(
            select(Campaign).where(
                Campaign.user_id == user_id, Campaign.quarter == quarter
            )
        ).scalar_one_or_none()

    def close_quarter(self, user: UserInDB, quarter: str, as_of: date) -> None:
        """Quarter rollover. An unfinished track PAUSES — that is the ONLY
        transition here. Milestones stay claimable; nothing expires, ever."""
        campaign = self._get(user.id, quarter)
        if campaign is None or campaign.status != "active":
            return
        if self._is_complete(campaign):
            campaign.status = "complete"
            self.db.flush()
            return
        campaign.status = "paused"
        self.db.flush()
        record_events(self.db, [GameEventDraft(
            stream="player", type="CampaignPaused",
            payload={"quarter": quarter, "date": as_of.isoformat()},
            idempotency_key=f"campaign_pause:{user.id}:{quarter}",
        )])
        self.db.flush()

    def _resume(self, user: UserInDB, campaign: Campaign, as_of: date) -> None:
        campaign.status = "active"
        self.db.flush()
        record_events(self.db, [GameEventDraft(
            stream="player", type="CampaignResumed",
            payload={"quarter": campaign.quarter, "date": as_of.isoformat()},
            idempotency_key=f"campaign_resume:{user.id}:{campaign.quarter}:{as_of.isoformat()}",
        )])
        self.db.flush()

    def _is_complete(self, campaign: Campaign) -> bool:
        granted = self._granted_keys(campaign)
        return all(m.key in granted for m in MILESTONES)

    # ── grants: computed from the event log (catch-up is free) ─────────────

    def _granted_keys(self, campaign: Campaign) -> set[str]:
        return {
            k for k in self.db.execute(
                select(CampaignProgress.milestone_key).where(
                    CampaignProgress.campaign_id == campaign.id
                )
            ).scalars()
        }

    def _event_count(self, event_type: str) -> int:
        return int(self.db.execute(
            select(func.count(GameEvent.id)).where(GameEvent.type == event_type)
        ).scalar_one())

    def compute_grants(self, user: UserInDB, as_of: date) -> list[str]:
        """Grant every milestone the event log already supports. Idempotent —
        this IS the retroactive catch-up path: a mid-quarter joiner whose log
        shows 2 sealed months is granted those milestones on first render."""
        campaign = self.ensure(user, as_of)
        granted = self._granted_keys(campaign)
        counts: dict[str, int] = {}
        newly: list[str] = []
        for m in MILESTONES:
            if m.key in granted:
                continue
            if m.source_event not in counts:
                counts[m.source_event] = self._event_count(m.source_event)
            if counts[m.source_event] >= m.threshold:
                self.db.add(CampaignProgress(
                    campaign_id=campaign.id, milestone_key=m.key,
                    granted_at=datetime.now(timezone.utc).isoformat(),
                ))
                self.db.flush()
                record_events(self.db, [GameEventDraft(
                    stream="player", type="CampaignMilestoneGranted",
                    payload={"milestone": m.key, "quarter": campaign.quarter},
                    idempotency_key=f"cmilestone:{user.id}:{campaign.id}:{m.key}",
                )])
                self.db.flush()
                newly.append(m.key)
        if newly and self._is_complete(campaign):
            campaign.status = "complete"
            self.db.flush()
        return newly

    # ── the read surface ────────────────────────────────────────────────────

    def view(self, user: UserInDB, as_of: date) -> dict:
        """The campaign payload. Deliberately carries NO time-remaining field —
        no countdown can render from data that does not exist."""
        self.compute_grants(user, as_of)
        campaign = self.ensure(user, as_of)
        granted = self._granted_keys(campaign)
        prestige = lifetime_prestige(self.db)
        return {
            "quarter": campaign.quarter,
            "arc_key": campaign.arc_key,
            "status": campaign.status,
            "rank": rank_for_prestige(prestige),
            "lifetime_prestige": prestige,
            "milestones": [
                {
                    "key": m.key,
                    "label_term": m.label_term,
                    "granted": m.key in granted,
                }
                for m in MILESTONES
            ],
        }
