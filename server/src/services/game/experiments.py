"""Experiment infrastructure — holdout, flags, exposures, kill switches (v4 §13).

**The holdout** answers the only question that matters: does the GAME add
anything ON TOP of the Money Spine? Holdout users get the spine ONLY — alerts,
the glanceable number, what-if, graduation — with the game mode locked ``off``
and game UI hidden. The spine is NEVER withheld: it's the evidenced part;
withholding it would be unethical and would also pollute the question.

**Flags E1-E9** each carry assignment (stable hash bucket), exposure logging
(``experiment_exposures`` — an OBSERVABILITY table; never ``game_events``),
and a documented DV query (the ``dv_query`` field — runnable prose, kept next
to the flag so the analysis is designed before the data arrives).

**Kill switches** are config, not migrations: killing a feature hides its UI
and pauses its jobs WITHOUT breaking folds/rebuilds — events keep their
meaning; only surfaces vanish. Each killable feature documents its FINANCIAL
kill criterion (target money metric vs holdout after a full campaign cycle).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import ExperimentExposure, User as UserORM

HOLDOUT_BUCKETS = 10  # 1 bucket in 10 → 10% holdout
COHORT_HOLDOUT = "holdout"
COHORT_GAME = "game"


# ── cohort assignment (stable, at first game activation) ────────────────────


def _bucket(seed: str, buckets: int) -> int:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return int(digest, 16) % buckets


def cohort_for(user_id: int, username: str) -> str:
    """Pure, stable assignment: the same user hashes to the same cohort across
    sessions, re-logins, and rebuilds. ~10% land in the holdout."""
    seed = f"cohort:{user_id}:{username}"
    return COHORT_HOLDOUT if _bucket(seed, HOLDOUT_BUCKETS) == 0 else COHORT_GAME


def ensure_cohort(db: Session, user_id: int) -> str:
    """The user's cohort, assigning it on first call (first game activation).
    Once written it is never re-derived — the column is the truth."""
    row = db.execute(
        select(UserORM).where(UserORM.id == user_id)
    ).scalar_one()
    if row.experiment_cohort:
        return row.experiment_cohort
    row.experiment_cohort = cohort_for(row.id, row.username)
    db.flush()
    return row.experiment_cohort


def is_holdout(db: Session, user_id: int) -> bool:
    row = db.execute(
        select(UserORM.experiment_cohort).where(UserORM.id == user_id)
    ).scalar_one_or_none()
    return row == COHORT_HOLDOUT


# ── the flag registry (E1-E9) ────────────────────────────────────────────────


@dataclass(frozen=True)
class Flag:
    key: str
    description: str
    arms: tuple[str, ...]
    dv_query: str  # the documented dependent-variable query (analysis-first)


FLAGS: dict[str, Flag] = {
    "E1": Flag(
        "E1", "Boss order: snowball-default vs avalanche-default ordering offer",
        ("snowball_first", "avalanche_first"),
        "DV: paydown rate (sum PaymentPosted cents / month) per arm; "
        "compare months 1-3 after first boss activation.",
    ),
    "E2": Flag(
        "E2", "Ward visibility: ward slots always shown vs shown on first earn",
        ("always_visible", "on_first_earn"),
        "DV: streak survival past first MISS (streak_state status != rebuilding "
        "7 days after first MISS) per arm.",
    ),
    "E3": Flag(
        "E3", "Bundled check-in: daily verb solo vs bundled with the number",
        ("solo_verb", "bundled"),
        "DV: hard-day action rate (action within 48h of Grace/negative-forecast "
        "trigger) per arm — metrics.hard_day_action_rate.",
    ),
    "E4": Flag(
        "E4", "Number presentation: plain Safe-to-Spend vs vitality framing",
        ("plain", "vitality"),
        "DV: alert→fix rate per arm — metrics.alert_fix_rate; guard: opt-out rate.",
    ),
    "E5": Flag(
        "E5", "Fade arm: graduation at 8 stable weeks vs no fade (control)",
        ("fade_8w", "no_fade"),
        "DV: savings rate vs baseline in weeks 9-16 per arm (does the quiet "
        "layer hold the habit?); guard: resurface rate.",
    ),
    "E6": Flag(
        "E6", "Streak display: count vs status-word (active/rebuilding) only",
        ("count", "status_word"),
        "DV: opt-out + slider-downgrade rate per arm; guard: on-time bills.",
    ),
    "E7": Flag(
        "E7", "Micro-ritual: collect affordance on vs auto-revealed tick",
        ("collect", "auto_reveal"),
        "DV: end-of-month spend distortion (last-3-days discretionary share) "
        "per arm — metrics.distortion_share (the TFI check).",
    ),
    "E8": Flag(
        "E8", "Alert timing: action-moment vs morning-digest delivery",
        ("action_moment", "morning_digest"),
        "DV: alert→fix rate within 48h per arm — the FCA replication.",
    ),
    "E9": Flag(
        "E9", "Heat arms: cosmetic-only vs self-funding sweep (tagged in 09)",
        ("cosmetic", "sweep"),
        "DV: verified underspend swept + contract met-rate per arm — "
        "metrics.e9_sweep_totals over heat_contracts.arm.",
    ),
}


def assign_arm(flag_key: str, user_id: int) -> str:
    """Stable per-(flag, user) arm assignment via hash bucket."""
    flag = FLAGS[flag_key]
    idx = _bucket(f"{flag_key}:{user_id}", len(flag.arms))
    return flag.arms[idx]


def log_exposure(
    db: Session, user_id: int, flag_key: str, arm: str, surface: str = ""
) -> None:
    """Record an exposure in the OBSERVABILITY table. Never a game event —
    the event log is domain history, not analytics (a test asserts zero
    ``game_events`` rows from exposure logging)."""
    db.add(ExperimentExposure(
        user_id=user_id, flag=flag_key, arm=arm, surface=surface,
        created_at=datetime.now(timezone.utc).isoformat(),
    ))
    db.flush()


# ── kill switches (config, never schema) ────────────────────────────────────


@dataclass
class KillSwitch:
    feature: str
    kill_criterion: str  # the FINANCIAL criterion that triggers the kill


# Each killable feature names the money metric that decides its fate after a
# full campaign cycle vs holdout. Killing = UI hidden + jobs paused; folds and
# rebuilds stay intact (events keep their meaning, surfaces vanish).
KILL_SWITCHES: dict[str, KillSwitch] = {
    "heat": KillSwitch(
        "heat",
        "Kill if verified underspend on contracted categories does not beat "
        "holdout after one full campaign cycle, or if the slider-downgrade "
        "rate among contract users exceeds 2x baseline.",
    ),
    "campaigns": KillSwitch(
        "campaigns",
        "Kill if savings rate vs baseline for campaign-active users does not "
        "beat holdout after one full quarter.",
    ),
    "challenges": KillSwitch(
        "challenges",
        "Kill if challenge-met users show no paydown/savings lift vs holdout "
        "after one full campaign cycle.",
    ),
    "expedition": KillSwitch(
        "expedition",
        "Kill if sealed-run users show no on-time-bills or savings lift vs "
        "holdout after one full campaign cycle.",
    ),
    "homestead": KillSwitch(
        "homestead",
        "Kill if homestead viewers show no savings-rate lift vs holdout after "
        "one full campaign cycle.",
    ),
    "bestiary": KillSwitch(
        "bestiary",
        "Kill if bestiary generation cost exceeds budget with no retention-"
        "neutral-or-better money metrics (it is flavor; the bar is do-no-harm).",
    ),
}

# Runtime kill set. Config-driven: seeded from settings.killed_features at
# import, mutable at runtime (an ops toggle, never a migration).
_KILLED: set[str] = set()


def _seed_from_settings() -> None:
    try:
        from ...settings import settings

        raw = getattr(settings, "killed_features", "") or ""
        for name in raw.split(","):
            name = name.strip()
            if name:
                _KILLED.add(name)
    except Exception:
        pass


_seed_from_settings()


def is_killed(feature: str) -> bool:
    return feature in _KILLED


def kill(feature: str) -> None:
    """Flip a feature off (ops action). Hides UI, pauses jobs; folds/rebuilds
    are untouched — no event changes meaning when a surface vanishes."""
    if feature not in KILL_SWITCHES:
        raise ValueError(f"unknown killable feature: {feature!r}")
    _KILLED.add(feature)


def revive(feature: str) -> None:
    _KILLED.discard(feature)


def killed_features() -> list[str]:
    return sorted(_KILLED)


# ── the client-facing flags payload ─────────────────────────────────────────


def flags_payload(db: Session, user_id: int) -> dict:
    """What the client needs to render honestly: the kill set and whether this
    user is holdout (game UI hidden, spine untouched)."""
    return {
        "killed": killed_features(),
        "holdout": is_holdout(db, user_id),
    }
