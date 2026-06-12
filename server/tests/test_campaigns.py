"""v4 package 10 — campaigns (spec test cases 1-5).

Non-expiry, retroactive catch-up, real-event milestones, the countdown ban,
and the monotonic sub-linear rank curve.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from server.src.db.models import Account as AccountORM, User as UserORM
from server.src.models import UserInDB
from server.src.services.game import folds as folds_mod
from server.src.services.game.campaigns import (
    MILESTONES,
    RANK_THRESHOLDS,
    STRUCTURAL_SOURCES,
    CampaignService,
    quarter_of,
    rank_for_prestige,
)
from server.src.services.game.events import GameEventDraft, record_events
from server.tests.integrity import finance_tables_fingerprint

Q2_DAY = date(2026, 5, 15)  # inside 2026-Q2
Q3_DAY = date(2026, 7, 3)  # inside 2026-Q3


@pytest.fixture
def user_acct(db_session):
    user = UserORM(username="camp", full_name="Camp U", email="camp@x.com",
                   hashed_password="x", savings_percent=0)
    db_session.add(user)
    db_session.flush()
    acct = AccountORM(name="Checking", type="checking", balance=500_00,
                      user_id=user.id)
    db_session.add(acct)
    db_session.flush()
    return user, acct


def _u(user):
    return UserInDB(id=user.id, username=user.username, email=user.email,
                    full_name=user.full_name, disabled=False, hashed_password="x")


def _emit(db, ev_type, payload, idem):
    record_events(db, [GameEventDraft(
        stream="player", type=ev_type, payload=payload, idempotency_key=idem,
    )])
    db.flush()


def _green_days(db, n, start=date(2026, 5, 1)):
    from datetime import timedelta

    for i in range(n):
        d = (start + timedelta(days=i)).isoformat()
        _emit(db, "UnderBudgetDayClosed", {"date": d}, f"green:t:{d}")


def _sealed_months(db, months):
    for m in months:
        _emit(db, "MonthSealed", {"month": m}, f"seal:t:{m}")


# ── 1: quarter end pauses; next-quarter activity resumes the SAME track ────


def test_unfinished_track_pauses_and_resumes_never_expires(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    svc = CampaignService(db_session)

    # Partial progress inside Q2 (some but not all milestones).
    _green_days(db_session, 5)
    _sealed_months(db_session, ["2026-04"])
    granted = svc.compute_grants(_u(user), Q2_DAY)
    assert "green_week_1" in granted and "month_sealed_1" in granted
    campaign = svc.ensure(_u(user), Q2_DAY)
    campaign_id = campaign.id
    assert campaign.status == "active"

    # Quarter ends with the track incomplete → paused (the ONLY transition).
    svc.close_quarter(_u(user), quarter_of(Q2_DAY), date(2026, 6, 30))
    assert campaign.status == "paused"

    # Next-quarter activity resumes the SAME track — same row, same quarter.
    resumed = svc.ensure(_u(user), Q3_DAY)
    assert resumed.id == campaign_id
    assert resumed.quarter == quarter_of(Q2_DAY)
    assert resumed.status == "active"

    # Milestones remain claimable after the pause/resume cycle.
    _sealed_months(db_session, ["2026-05"])
    later = svc.compute_grants(_u(user), Q3_DAY)
    assert "month_sealed_2" in later

    # No expiry path exists BY DESIGN: across the whole lifecycle no status
    # outside the closed enum ever appears, and the model documents the enum
    # without an expired member (attempting to "expire" has no code to call).
    from server.src.db.models import Campaign as CampaignORM
    from sqlalchemy import select

    statuses = set(db_session.execute(select(CampaignORM.status)).scalars())
    assert statuses <= {"active", "paused", "complete"}
    import server.src.services.game.campaigns as campaigns_mod
    import inspect

    source = inspect.getsource(campaigns_mod)
    assert 'status = "expired"' not in source
    assert "'expired'" not in source


# ── 2: mid-quarter joiner — the log makes catch-up free ────────────────────


def test_mid_quarter_joiner_auto_granted_from_event_log(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    # The event log already shows 2 sealed months BEFORE the user ever touches
    # a campaign surface.
    _sealed_months(db_session, ["2026-03", "2026-04"])

    view = CampaignService(db_session).view(_u(user), Q2_DAY)  # first render
    granted = {m["key"] for m in view["milestones"] if m["granted"]}
    assert {"month_sealed_1", "month_sealed_2"} <= granted


# ── 3: milestone sources walk (never logins/opens/views) ───────────────────


def test_every_milestone_derives_from_real_events():
    from server.src.services.game.xp import XP_BEARING

    engagement = {"SheetViewed", "LoggedIn", "Collected", "ModeChanged",
                  "AlertDelivered", "AlertFired"}
    for m in MILESTONES:
        assert (
            m.source_event in XP_BEARING or m.source_event in STRUCTURAL_SOURCES
        ), f"milestone {m.key} derives from unsanctioned event {m.source_event}"
        assert m.source_event not in engagement, (
            f"milestone {m.key} derives from an engagement event — forbidden"
        )


# ── 4: the countdown ban (zero time-pressure vocabulary) ───────────────────


def test_campaign_payload_carries_no_countdown(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    _green_days(db_session, 5)
    view = CampaignService(db_session).view(_u(user), Q2_DAY)
    rendered = json.dumps(view).lower()
    for banned in ("expires", "expired", "last chance", "hurry", "days left",
                   "time left", "remaining", "countdown", "deadline"):
        assert banned not in rendered, f"countdown vocabulary leaked: {banned!r}"
    # And no field even SHAPED like a countdown.
    for key in view:
        assert "left" not in key and "remain" not in key and "expir" not in key


# ── 5: rank curve — monotonic, sub-linear, never decreases ─────────────────


def test_rank_curve_monotonic_and_sublinear():
    order = ["E", "D", "C", "B", "A", "S"]
    last_idx = 0
    for prestige in range(0, 200):
        idx = order.index(rank_for_prestige(prestige))
        assert idx >= last_idx, "rank decreased as prestige grew"
        last_idx = idx
    # Sub-linear: each rank step costs MORE prestige than the one before.
    floors = [f for f, _ in RANK_THRESHOLDS]
    gaps = [b - a for a, b in zip(floors, floors[1:])]
    assert gaps == sorted(gaps), "rank thresholds must grow super-linearly"
    assert rank_for_prestige(0) == "E"
    assert rank_for_prestige(10_000) == "S"


# ── Law 1: campaigns never touch financial truth ───────────────────────────


def test_fingerprint_unchanged_across_campaign_lifecycle(db_session, user_acct):
    user, _ = user_acct
    folds_mod.register_builtin_folds()
    _green_days(db_session, 5)
    _sealed_months(db_session, ["2026-04"])
    before = finance_tables_fingerprint(db_session)
    svc = CampaignService(db_session)
    svc.view(_u(user), Q2_DAY)
    svc.close_quarter(_u(user), quarter_of(Q2_DAY), date(2026, 6, 30))
    svc.ensure(_u(user), Q3_DAY)
    after = finance_tables_fingerprint(db_session)
    assert before == after
