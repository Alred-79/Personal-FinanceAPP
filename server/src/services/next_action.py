"""W8 — "One thing today": the unified next-action ranker.

There is no single place today that answers "what is the ONE thing worth doing?"
— bridges, rule proposals, challenges, streak recovery and auditor findings each
live in their own surface. For an underserved (e.g. neurodivergent) segment a wall
of competing nudges is the failure mode; the strength we already have (no-break
streaks + grace + no-shame) only pays off if it is presented as a single, calm,
never-shaming next step.

:func:`compute` aggregates every actionable source, ranks them by a STRICT,
deterministic priority, and returns EXACTLY ONE recommendation (or a calm
"you're all set" when nothing is actionable — it NEVER invents a task). The return
shape is intentionally small: ``{action_type, entity_id, copy}`` plus a couple of
display hints.

Guardrails:
  * **B1 (RLS):** this is request-path only — the ``GET /next-action/`` router binds
    the tenant via ``get_tenant_db`` before calling :func:`compute`. No background
    job here.
  * **B3 (firewall):** every ``copy`` string is screened through ``screen_output``
    (no-shame / non-directive); a blocked string falls back to a bare neutral
    factual line, never the firewall's redirect placeholder.
  * **B4 (ship-dark):** the ranker runs regardless of the ``neurodivergent_mode``
    flag — the endpoint always works. Only the CLIENT defaulting to the single
    surface (and the grace widening) is flag-gated.

The priority order (highest first), per the W8 spec:
  1. an open assisted-action **bridge due** (the user already committed to a real
     move; due/overdue beats everything),
  2. a pending **``rule_proposal``** to confirm (a one-tap approval that's waiting),
  3. an **active challenge ending soon** (time-boxed; closes if ignored),
  4. **streak recovery** (a rebuilding/reviving streak — gentle, never shaming),
  5. the **top auditor finding** (informational; lowest because it's not a
     commitment the user already made).
Ties within a source break deterministically (oldest/soonest first).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    AssistedAction as AssistedActionORM,
    Challenge as ChallengeORM,
    Notification as NotificationORM,
)
from ..money import cents_to_dollars
from .game.firewall import screen_output

log = logging.getLogger(__name__)

# A bridge the user acted on (or was proposed) is "due" once this many days have
# passed since it was created without verification — the soft point at which "the
# one thing today" becomes following through on it. Bridges the user explicitly
# marked done but that haven't reconciled also count as due (the gentle "did that
# go through?" follow-up).
_BRIDGE_DUE_AFTER_DAYS = 0  # proposed/acknowledged bridges are actionable immediately
# A challenge counts as "ending soon" within this many days of its ``ends_on``.
_CHALLENGE_SOON_DAYS = 3

# Statuses of an assisted-action bridge that are still open / actionable.
_OPEN_BRIDGE = ("proposed", "acknowledged", "confirmed_done")


@dataclass(frozen=True)
class NextAction:
    """One recommended action. ``entity_id`` references the underlying row so the
    client can deep-link (a bridge id, a notification id, a challenge id, etc.);
    it is ``None`` for sourceless actions (streak recovery, all-set)."""

    action_type: str
    entity_id: Optional[int]
    copy: str
    # Display hints (not load-bearing for the ranking): a deep link + a short
    # category label so the client can pick an icon without re-deriving it.
    deep_link: Optional[str] = None
    source: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "entity_id": self.entity_id,
            "copy": self.copy,
            "deep_link": self.deep_link,
            "source": self.source,
        }


# The calm empty state — NEVER an invented task (W8 edge case). Authored
# non-directive + no-shame; still screened for belt-and-suspenders.
_ALL_SET_COPY = (
    "You're all set for today. Nothing needs your attention right now — "
    "your goals and history are right where you left them."
)


def _safe_copy(text: str, *, fallback: str) -> str:
    """Screen one copy string through the output firewall (B3). A blocked string
    is replaced with a bare neutral factual ``fallback`` — never the firewall's
    redirect placeholder, which would read oddly as a next-action headline, and
    never shame."""
    verdict = screen_output(text or "", plain=True)
    return text if not verdict.blocked else fallback


def _parse_iso(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except (TypeError, ValueError):
        try:
            return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None


# ── individual source probes (each returns at most ONE candidate) ─────────────


def _bridge_candidate(
    db: Session, user_id: int, today: date
) -> Optional[NextAction]:
    """The single most-overdue open assisted-action bridge (Pillar 2C). Oldest
    open bridge wins — it's the commitment that's been waiting longest."""
    bridges = (
        db.execute(
            select(AssistedActionORM)
            .where(
                AssistedActionORM.user_id == user_id,
                AssistedActionORM.status.in_(_OPEN_BRIDGE),
            )
            .order_by(AssistedActionORM.id.asc())
        )
        .scalars()
        .all()
    )
    for bridge in bridges:
        created = _parse_iso(bridge.created_at)
        if created is not None and (today - created).days < _BRIDGE_DUE_AFTER_DAYS:
            continue
        dollars = cents_to_dollars(int(bridge.amount_cents or 0))
        kind_label = (bridge.kind or "").replace("_", " ")
        copy = _safe_copy(
            f"Follow through on the ${dollars:,.2f} {kind_label} in your bank, "
            "then it'll reconcile automatically on your next sync.",
            fallback=f"A ${dollars:,.2f} {kind_label} is ready for you to complete.",
        )
        return NextAction(
            action_type="bridge_due",
            entity_id=bridge.id,
            copy=copy,
            deep_link="/assisted-actions",
            source="bridge",
        )
    return None


def _proposal_candidate(
    db: Session, user_id: int, today: date
) -> Optional[NextAction]:
    """The single oldest unread ``rule_proposal`` notification waiting for a
    one-tap confirm (C1/C3). Unread because a read proposal has been seen; we
    surface the one that's been waiting longest."""
    note = db.execute(
        select(NotificationORM)
        .where(
            NotificationORM.user_id == user_id,
            NotificationORM.type == "rule_proposal",
            NotificationORM.read == 0,
        )
        .order_by(NotificationORM.id.asc())
    ).scalars().first()
    if note is None:
        return None
    copy = _safe_copy(
        note.message or "An auto-fund proposal is waiting for your one-tap approval.",
        fallback="An auto-fund proposal is waiting for your one-tap approval.",
    )
    return NextAction(
        action_type="rule_proposal",
        entity_id=note.id,
        copy=copy,
        deep_link="/notifications",
        source="proposal",
    )


def _challenge_candidate(
    db: Session, user_id: int, today: date
) -> Optional[NextAction]:
    """The single active challenge ENDING SOONEST within the window. Uses
    ``ChallengeService.active`` semantics (status == 'active') and filters to
    those whose ``ends_on`` is within ``_CHALLENGE_SOON_DAYS``."""
    rows = (
        db.execute(
            select(ChallengeORM).where(
                ChallengeORM.user_id == user_id,
                ChallengeORM.status == "active",
            )
        )
        .scalars()
        .all()
    )
    soonest: Optional[ChallengeORM] = None
    soonest_end: Optional[date] = None
    for ch in rows:
        end = _parse_iso(ch.ends_on)
        if end is None:
            continue
        days_left = (end - today).days
        if days_left < 0 or days_left > _CHALLENGE_SOON_DAYS:
            continue
        if soonest_end is None or end < soonest_end or (
            end == soonest_end and (soonest is None or ch.id < soonest.id)
        ):
            soonest, soonest_end = ch, end
    if soonest is None or soonest_end is None:
        return None
    days_left = (soonest_end - today).days
    when = "today" if days_left == 0 else (
        "tomorrow" if days_left == 1 else f"in {days_left} days"
    )
    copy = _safe_copy(
        f"Your active challenge wraps up {when} — you're on track to finish it.",
        fallback=f"An active challenge ends {when}.",
    )
    return NextAction(
        action_type="challenge_ending",
        entity_id=soonest.id,
        copy=copy,
        deep_link="/campaigns",
        source="challenge",
    )


def _streak_recovery_candidate(
    db: Session, user_id: int, today: date
) -> Optional[NextAction]:
    """A gentle streak-recovery nudge when the streak machine is rebuilding or
    reviving. NEVER touches the streak machine and NEVER shames the lapse — the
    copy frames it as a fresh start, not a loss (daily.py rebuilds, never breaks).

    Reads the ``streak_state`` projection (the same view the daily surface shows).
    Only fires when there's something to recover (rebuilding/reviving)."""
    from .game.daily import streak_view, REBUILDING, REVIVING

    try:
        view = streak_view(db)
    except Exception:  # noqa: BLE001 — the game projection is optional/deferred
        return None
    status = view.get("status")
    if status not in (REBUILDING, REVIVING):
        return None
    best = int(view.get("best") or 0)
    if view.get("reviving"):
        copy = _safe_copy(
            "You can pick your streak back up — three steady days revives it. "
            f"Your best run of {best} is safe.",
            fallback="You can pick your streak back up whenever you're ready.",
        )
    else:
        copy = _safe_copy(
            "Your streak is rebuilding — one small step today keeps it going. "
            f"Your best run of {best} is right where you left it.",
            fallback="Your streak is rebuilding whenever you're ready.",
        )
    return NextAction(
        action_type="streak_recovery",
        entity_id=None,
        copy=copy,
        deep_link="/",
        source="streak",
    )


def _auditor_candidate(
    db: Session, user_id: int, today: date
) -> Optional[NextAction]:
    """The single highest-severity unread auditor finding, surfaced READ-ONLY
    (we do NOT run the nightly auditor here — that's a background job, B1). We
    read the most recent unread auditor-typed notification the job already
    wrote."""
    auditor_types = (
        "overdraft_risk",
        "merchant_lifecycle",
        "price_creep",
        "anomaly",
        "budget_overrun",
    )
    note = db.execute(
        select(NotificationORM)
        .where(
            NotificationORM.user_id == user_id,
            NotificationORM.type.in_(auditor_types),
            NotificationORM.read == 0,
        )
        .order_by(NotificationORM.created_at.desc(), NotificationORM.id.desc())
    ).scalars().first()
    if note is None:
        return None
    copy = _safe_copy(
        note.message or "Your nightly review surfaced something worth a look.",
        fallback="Your nightly review surfaced something worth a look.",
    )
    return NextAction(
        action_type="auditor_finding",
        entity_id=note.id,
        copy=copy,
        deep_link="/forecast",
        source="auditor",
    )


# The strict ranking: each probe is tried in priority order; the FIRST non-None
# candidate is THE one thing today. This is how "exactly one" is guaranteed —
# we never collect a list and trim it; we short-circuit on the first hit.
_RANKED_PROBES = (
    _bridge_candidate,
    _proposal_candidate,
    _challenge_candidate,
    _streak_recovery_candidate,
    _auditor_candidate,
)


def compute(db: Session, user_id: int, *, today: Optional[date] = None) -> dict[str, Any]:
    """Return EXACTLY ONE next action for the user, or the calm all-set state.

    Tries each source in strict priority order and returns the first hit. When
    nothing is actionable it returns a calm "you're all set" — it NEVER invents a
    task (W8 edge case). The caller (the router) has already bound the RLS tenant.
    """
    today = today or date.today()
    for probe in _RANKED_PROBES:
        try:
            candidate = probe(db, user_id, today)
        except Exception:  # noqa: BLE001 — one bad source can't break the surface
            log.exception("next_action probe %s failed: user=%s", probe.__name__, user_id)
            candidate = None
        if candidate is not None:
            return {"has_action": True, **candidate.as_dict()}
    # Nothing actionable → the calm empty state (never a fabricated task).
    return {
        "has_action": False,
        "action_type": "all_set",
        "entity_id": None,
        "copy": _safe_copy(_ALL_SET_COPY, fallback="You're all set for today."),
        "deep_link": None,
        "source": None,
    }
