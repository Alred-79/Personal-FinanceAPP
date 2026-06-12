"""XP hygiene — the allowlist and the level curve (v4 §6.1, §9.1).

OSC evidence: points attached to anything maximize that thing. So XP attaches
ONLY to verified financial actions. Every registered event type must be
explicitly classified as XP-bearing or XP-forbidden — a new, unclassified type
makes the registry-walk test (test 1) fail, which is intended friction: adding
XP to a new event is a deliberate, reviewed act.

``ConsistencyVerb`` is the one argued exception (a daily "I checked in"): it is
XP-bearing but **capped** at ≤10% of the median money-action XP value per day,
so it can never compete with real actions (v4 §9.1).
"""

from __future__ import annotations

import math

from .events import register_event_type

# Event types that grant XP. The value is the base XP per occurrence. Only
# verified financial actions appear here.
XP_BEARING: dict[str, int] = {
    "AllocationMade": 20,
    "RuleExecuted": 15,
    "BillPaidOnTime": 25,
    "UnderBudgetDayClosed": 10,
    "WhatIfCommitted": 20,
    # AlertFixApplied is conditional: only non-checklist fix kinds award XP
    # (a checklist step is unverified). See xp_for_event.
    "AlertFixApplied": 15,
    # PaymentPosted lands in package 06; pre-listed so its handler is allowed.
    "PaymentPosted": 20,
    # The capped consistency verb (package 05 emits it).
    "ConsistencyVerb": 5,
}

# Event types that must NEVER grant XP. Engagement-shaped events (opening a
# screen, a delivered notification, a settings change) belong here — attaching
# XP to them would reward the wrong behavior.
XP_FORBIDDEN: set[str] = {
    "BackfillSnapshot",
    "SyncGapOpened",
    "SyncGapClosed",
    "TxnPosted",  # a posted txn is data, not a rewarded action by itself
    "TxnCorrected",  # corrections adjust baselines, never award
    "TxnReversed",
    "MonthSealed",
    "XpAwarded",  # the award record itself is not re-awarding
    "AlertFired",  # a delivered/fired alert is engagement, not an action
    # Engagement probes (some only exist in tests) — listed so the law is
    # explicit and future engagement events have a home.
    "ModeChanged",
    "SheetViewed",
    "LoggedIn",
    "Collected",  # collect-without-accrual
    "AlertDelivered",
    # Package 05 — the daily skeleton. The day-close and streak machinery is
    # structural, not a rewarded action (the XP for a green day rides on the
    # separate XP-bearing UnderBudgetDayClosed event, not on DayClosed itself).
    "DayClosed",
    "WardConsumed",
    "WardEarned",
    "RevivalOffered",
    "RevivalCompleted",
    "RevivalEnded",
    "TickAccrued",
    "TickCollected",  # collect is presentation — reveals already-accrued XP
    # Basic Grace (pkg 05) — easing off in a hard month grants no XP, ever.
    "GraceApplied",
    "GraceLifted",
    # Package 06 — debt boss. These are projection events over real money (the
    # XP for a real payment rides on PaymentPosted, which is XP_BEARING). The
    # boss-damage/heal/phase events themselves never award XP.
    "BossDamaged",
    "BossHealed",
    "BossEmpowered",
    "BossPhaseBroken",
    "BossDefeated",
    "BossSealed",
    "BossBanished",
    "BossCorrected",
    # Package 07 — the Chronicler. Generating flavor text is never a rewarded
    # action (Law 2: flavor never feeds engine state, including XP).
    "ChapterGenerated",
    # Package 08 — the Expedition. Drafting a run, offering a modifier, and
    # minting prestige are structural/scoring events, not money actions; no XP.
    "RunDrafted",
    "ModifierOffered",
    "PrestigeMinted",
    # Package 09 — depth. Crossing a real milestone grants a homestead XP
    # MULTIPLIER (a ratchet applied at accrual time), not flat XP on the event.
    "MilestoneReached",
}

# The one capped exception. Consistency XP per day is capped at 10% of the
# median money-action XP value so it can never out-earn a real action.
_MONEY_ACTION_VALUES = sorted(
    v for k, v in XP_BEARING.items() if k != "ConsistencyVerb"
)
_MEDIAN_MONEY_XP = _MONEY_ACTION_VALUES[len(_MONEY_ACTION_VALUES) // 2]
CONSISTENCY_DAILY_CAP = max(int(_MEDIAN_MONEY_XP * 0.10), 1)

# Make every classified type a valid event the substrate accepts. XP-bearing
# types (AllocationMade, BillPaidOnTime, …) and the engagement-shaped forbidden
# types (ModeChanged, SheetViewed, …) are registered so record_events won't
# reject them. (TxnPosted/Corrected/… were already registered in events.py.)
for _t in list(XP_BEARING) + list(XP_FORBIDDEN):
    register_event_type(_t, 1)

# Level curve constant. level = floor(sqrt(xp / K)). K is chosen so a typical
# engaged month (~3-5 money actions/week ≈ 60 actions × ~18 XP ≈ 1080 XP/mo)
# yields ~1-2 levels early and slows later. K=120 → 1080 XP ≈ level 3 in month 1,
# and the gap between levels widens (sqrt curve) as XP grows.
LEVEL_K = 120


def is_classified(event_type: str) -> bool:
    """Whether *event_type* is explicitly XP-bearing or XP-forbidden."""
    return event_type in XP_BEARING or event_type in XP_FORBIDDEN


def xp_for_event(event_type: str, payload: dict | None = None) -> int:
    """Base XP an event grants (before the consistency daily cap / clamp).

    Returns 0 for forbidden types. ``AlertFixApplied`` only awards for
    non-checklist fix kinds (a checklist step is unverified).
    """
    if event_type not in XP_BEARING:
        return 0
    if event_type == "AlertFixApplied":
        kind = (payload or {}).get("fix_kind")
        if kind == "checklist":
            return 0
    return XP_BEARING[event_type]


def level_for_xp(xp: int) -> int:
    """Sub-linear level from total XP: ``floor(sqrt(xp / K))``.

    Monotonic non-decreasing in xp; the gap between consecutive levels grows, so
    early levels come fast and later ones slow. Never returns a negative level
    (xp is clamped non-negative upstream).
    """
    if xp <= 0:
        return 0
    return math.isqrt(xp // LEVEL_K)
