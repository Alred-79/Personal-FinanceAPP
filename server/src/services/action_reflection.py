"""W4 — Reconciliation→planning feedback loop (reflection + automation offers).

A nightly job reads each user's ``AssistedAction`` rows (which already persist
``kind``, ``status``, ``created_at``, ``resolved_at``, ``amount_cents``,
``dest_ref`` / ``how_json.goal_id``), aggregates *follow-through* over a trailing
window, and produces two outputs — WITHOUT ever moving money or accumulating an
episodic event log:

1. **Reflection memory (Tier 1).** ONE *regenerated, generalized* fact per user,
   written through :func:`user_memory.set_user_fact` (``source="deterministic"``,
   PII-scrubbed). The sentence is factual and NON-directive — it states what the
   user tends to do, never what they *should* do — and is run through the output
   firewall (``screen_output``); a blocked candidate is dropped, never stored.
   One key (``action_followthrough``), upserted each run → no episodic bloat
   (the agent-memory literature's "active compression" requirement, see
   docs/PLAN-router-and-feedback-loop.md).

2. **Automation offer (Tier 2).** When a stable pattern verifies repeatedly
   (same ``kind`` + goal/``dest_ref`` + ~amount, ≥ ``min_repeats`` on a regular
   cadence) and no equivalent ``Rule`` exists, surface ONE idempotent
   ``Notification(type="rule_proposal", ref="rule_suggest:{kind}:{dest}:{period}")``
   proposing a ``create_rule`` (``allocate``) automation. The rule stays
   **propose-only**: tapping the offer mints a ``create_rule`` token (C2); the
   user confirms via ``/assistant/actions/confirm/``; nothing auto-fires.

No new tables: inputs live on ``AssistedAction``; outputs go to ``user_memory``
(new key, code-only) and ``Notification`` (existing).

RLS (guardrail B1): the nightly job is responsible for establishing tenant
context per user before reading that user's rows. See ``scheduler.job_action_reflection``.
This module's functions take an explicit ``user_id`` and assume the caller has
already bound the tenant (or is running under the BYPASSRLS scheduler role).
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    AssistedAction as AssistedActionORM,
    Goal as GoalORM,
    Notification as NotificationORM,
    Rule as RuleORM,
)
from .game.firewall import screen_output
from . import user_memory

log = logging.getLogger(__name__)

# The single memory key this feature owns (C5 — added to MEMORY_KEYS).
FOLLOWTHROUGH_KEY = "action_followthrough"

# A pattern only earns an offer when its verified occurrences land on a roughly
# regular cadence. We bucket the median inter-occurrence gap into a coarse period
# label used in the rule name and the dedup ``ref``.
_PERIOD_BUCKETS = (
    (10, "weekly"),
    (24, "biweekly"),
    (45, "monthly"),
    (135, "quarterly"),
)

# Statuses we treat as a "did not follow through" outcome (denominator of the
# follow-through rate alongside ``verified``).
_NEGATIVE_STATUSES = ("dismissed", "expired")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(value[:19])
        except (TypeError, ValueError):
            return None


def _loads(text: Optional[str]) -> dict[str, Any]:
    try:
        out = json.loads(text) if text else {}
        return out if isinstance(out, dict) else {}
    except (TypeError, ValueError):
        return {}


def _dest_label(row: AssistedActionORM) -> Optional[str]:
    """The stable destination identity of an action for pattern grouping.

    Prefers an earmark's ``how_json.goal_id`` (the common goal-funding case),
    falling back to ``dest_ref``. Returns None when neither is present (an
    untargeted action can't seed a per-destination rule offer)."""
    how = _loads(row.how_json)
    goal_id = how.get("goal_id")
    if goal_id is not None:
        return f"goal:{goal_id}"
    if row.dest_ref:
        return f"dest:{row.dest_ref}"
    return None


def _within_window(row: AssistedActionORM, since: datetime) -> bool:
    created = _parse_dt(row.created_at)
    if created is None:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created >= since


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_outcomes(db: Session, user_id: int, window_days: int) -> dict[str, Any]:
    """Per-``kind`` follow-through stats over the trailing ``window_days``.

    Returns ``{"per_kind": {kind: {proposed, verified, dismissed, expired,
    follow_through_rate, median_latency_days}}, "total": int}``. Follow-through
    rate = verified / (verified + dismissed + expired); median latency is over
    the VERIFIED rows' ``created_at``→``resolved_at`` deltas (days). A kind with
    no resolved outcomes has ``follow_through_rate=None``.
    """
    from datetime import timedelta

    since = datetime.now(timezone.utc) - timedelta(days=max(0, int(window_days)))

    rows = (
        db.execute(
            select(AssistedActionORM).where(AssistedActionORM.user_id == user_id)
        )
        .scalars()
        .all()
    )
    rows = [r for r in rows if _within_window(r, since)]

    per_kind: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = per_kind.setdefault(
            row.kind,
            {
                "proposed": 0,
                "verified": 0,
                "dismissed": 0,
                "expired": 0,
                "_latencies": [],
            },
        )
        bucket["proposed"] += 1
        status = row.status
        if status == "verified":
            bucket["verified"] += 1
            created = _parse_dt(row.created_at)
            resolved = _parse_dt(row.resolved_at)
            if created is not None and resolved is not None:
                bucket["_latencies"].append(
                    (resolved - created).total_seconds() / 86400.0
                )
        elif status == "dismissed":
            bucket["dismissed"] += 1
        elif status == "expired":
            bucket["expired"] += 1

    for bucket in per_kind.values():
        resolved_n = bucket["verified"] + bucket["dismissed"] + bucket["expired"]
        bucket["follow_through_rate"] = (
            bucket["verified"] / resolved_n if resolved_n else None
        )
        lat = bucket.pop("_latencies")
        bucket["median_latency_days"] = (
            round(statistics.median(lat), 1) if lat else None
        )

    return {"per_kind": per_kind, "total": len(rows)}


# ---------------------------------------------------------------------------
# Fact synthesis (Tier 1)
# ---------------------------------------------------------------------------

def synthesize_fact(stats: dict[str, Any]) -> Optional[str]:
    """One short, FACTUAL, NON-directive sentence — or None on sparse data.

    Describes what the user *tends to do* with assisted actions (and how fast),
    never what they *should* do. Returns None when there is too little resolved
    history to generalize, so no fact is written. The caller additionally screens
    the sentence through the output firewall and drops it if blocked.
    """
    per_kind = stats.get("per_kind") or {}
    # Only kinds with at least one resolved outcome can characterize behavior.
    resolved_kinds = {
        kind: b
        for kind, b in per_kind.items()
        if (b["verified"] + b["dismissed"] + b["expired"]) > 0
    }
    if not resolved_kinds:
        return None

    # The kind the user acts on MOST (highest verified count, then highest rate)
    # — used to phrase a positive, factual tendency. The kind they act on LEAST
    # adds a contrasting clause only when it's clearly low and well-sampled.
    def _readable(kind: str) -> str:
        return kind.replace("_", " ")

    top_kind, top = max(
        resolved_kinds.items(),
        key=lambda kv: (kv[1]["verified"], kv[1]["follow_through_rate"] or 0),
    )
    if top["verified"] == 0:
        # Nobody followed through on anything resolved — state that factually.
        return "Tends not to act on assisted-action suggestions so far."

    latency = top["median_latency_days"]
    if latency is not None and latency <= 1.5:
        speed = "within about a day"
    elif latency is not None and latency <= 4:
        speed = "within a few days"
    elif latency is not None:
        speed = f"within about {int(round(latency))} days"
    else:
        speed = None

    parts = [
        f"Tends to act on {_readable(top_kind)} suggestions"
        + (f" {speed}" if speed else "")
    ]

    # A contrasting low-follow-through kind (well-sampled, clearly lower).
    low_candidates = [
        (kind, b)
        for kind, b in resolved_kinds.items()
        if kind != top_kind
        and (b["verified"] + b["dismissed"] + b["expired"]) >= 2
        and (b["follow_through_rate"] or 0) <= 0.34
    ]
    if low_candidates:
        low_kind, _ = min(
            low_candidates, key=lambda kv: kv[1]["follow_through_rate"] or 0
        )
        parts.append(f"tends not to act on {_readable(low_kind)} suggestions")

    return "; ".join(parts) + "."


# ---------------------------------------------------------------------------
# Automation detection (Tier 2)
# ---------------------------------------------------------------------------

def _period_label(gaps: list[float]) -> Optional[str]:
    """Bucket the median inter-occurrence gap (days) into a cadence label, or
    None if the cadence is too irregular / sparse to name."""
    if not gaps:
        return None
    median_gap = statistics.median(gaps)
    for upper, label in _PERIOD_BUCKETS:
        if median_gap <= upper:
            return label
    return None


def detect_automatable(
    db: Session, user_id: int, window_days: int, min_repeats: int
) -> list[dict[str, Any]]:
    """Patterns eligible for a one-tap rule offer.

    A pattern is ``(kind, dest, ~amount, period)`` that VERIFIED ≥ ``min_repeats``
    times on a roughly regular cadence within the window, where ``dest`` resolves
    to a goal (so an ``allocate`` rule can target it) and NO equivalent enabled
    ``Rule`` already covers it. Returns a list of candidate dicts; the caller
    mints ≤1 idempotent offer per candidate. Pure (no writes)."""
    from datetime import timedelta

    since = datetime.now(timezone.utc) - timedelta(days=max(0, int(window_days)))
    rows = (
        db.execute(
            select(AssistedActionORM).where(
                AssistedActionORM.user_id == user_id,
                AssistedActionORM.status == "verified",
            )
        )
        .scalars()
        .all()
    )
    rows = [r for r in rows if _within_window(r, since)]

    # Group verified actions by (kind, dest).
    groups: dict[tuple[str, str], list[AssistedActionORM]] = {}
    for row in rows:
        dest = _dest_label(row)
        if dest is None:
            continue
        groups.setdefault((row.kind, dest), []).append(row)

    candidates: list[dict[str, Any]] = []
    for (kind, dest), members in groups.items():
        if len(members) < min_repeats:
            continue
        # Only goal-targeted patterns can compile to an allocate rule.
        if not dest.startswith("goal:"):
            continue
        goal_id = int(dest.split(":", 1)[1])
        goal = db.execute(
            select(GoalORM).where(
                GoalORM.id == goal_id, GoalORM.user_id == user_id
            )
        ).scalar_one_or_none()
        if goal is None:
            continue
        # Cadence: median gap between consecutive verified occurrences.
        dates = sorted(
            d
            for d in (_parse_dt(m.created_at) for m in members)
            if d is not None
        )
        gaps = [
            (dates[i + 1] - dates[i]).total_seconds() / 86400.0
            for i in range(len(dates) - 1)
        ]
        period = _period_label(gaps)
        if period is None:
            continue  # too irregular to call a cadence
        # ~amount: the median verified amount (integer cents — guardrail B6).
        amount_cents = int(
            statistics.median(sorted(m.amount_cents for m in members))
        )
        if amount_cents <= 0:
            continue
        # Skip if an equivalent enabled allocate rule already targets this goal.
        if _rule_covers(db, user_id, goal_id):
            continue
        candidates.append(
            {
                "kind": kind,
                "dest": dest,
                "goal_id": goal_id,
                "goal_name": goal.name,
                "amount_cents": amount_cents,
                "period": period,
                "count": len(members),
            }
        )
    return candidates


def _rule_covers(db: Session, user_id: int, goal_id: int) -> bool:
    """True if an enabled ``allocate`` rule already targets this goal."""
    existing = db.execute(
        select(RuleORM.id).where(
            RuleORM.user_id == user_id,
            RuleORM.action_type == "allocate",
            RuleORM.target_kind == "goal",
            RuleORM.target_id == goal_id,
            RuleORM.enabled == 1,
        )
    ).first()
    return existing is not None


def _offer_ref(candidate: dict[str, Any]) -> str:
    """Stable dedup key for a rule-suggestion notification. Includes the period
    so a changed cadence can re-offer, but NOT the exact amount (a few-cent drift
    shouldn't re-surface a declined offer)."""
    return f"rule_suggest:{candidate['kind']}:{candidate['dest']}:{candidate['period']}"


def _offer_exists(db: Session, user_id: int, ref: str) -> bool:
    """Read-or-unread dedup AND dismissal suppression: any notification with this
    ref (the user may have seen and dismissed it) blocks a re-offer."""
    return (
        db.execute(
            select(NotificationORM.id).where(
                NotificationORM.user_id == user_id,
                NotificationORM.ref == ref,
            )
        ).first()
        is not None
    )


# ---------------------------------------------------------------------------
# Per-user orchestration
# ---------------------------------------------------------------------------

def run_for_user(
    db: Session,
    user_id: int,
    *,
    window_days: int,
    min_repeats: int,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Synthesize the reflection fact and fire ≤1 idempotent rule offer per
    automatable pattern, for ONE user. Assumes the caller has already bound the
    RLS tenant for this user (guardrail B1). Returns a summary dict.

    Calls :func:`assistant_service.invalidate_agent` after a fact change so the
    Clerk re-bakes its prompt with the new fact promptly."""
    summary: dict[str, Any] = {
        "fact_written": False,
        "fact": None,
        "offers": 0,
    }

    # ── Tier 1: reflection fact ──────────────────────────────────────────
    stats = aggregate_outcomes(db, user_id, window_days)
    fact = synthesize_fact(stats)
    if fact is not None:
        # B3: the synthesized fact must pass the SAME output firewall used on the
        # model's replies. A candidate that reads as advice/shame is dropped, not
        # stored — so it can never be re-injected into a later prompt.
        if not screen_output(fact, plain=True).blocked:
            try:
                user_memory.set_user_fact(
                    db,
                    user_id,
                    FOLLOWTHROUGH_KEY,
                    fact,
                    source="deterministic",
                )
                summary["fact_written"] = True
                summary["fact"] = fact
                _invalidate_agent(user_id)
            except user_memory.MemoryError:
                log.exception("reflection fact upsert failed: user=%s", user_id)

    # ── Tier 2: automation offers ────────────────────────────────────────
    candidates = detect_automatable(db, user_id, window_days, min_repeats)
    created = 0
    for candidate in candidates:
        ref = _offer_ref(candidate)
        if _offer_exists(db, user_id, ref):
            continue  # already offered (read/unread) or previously dismissed
        dollars = candidate["amount_cents"] / 100
        db.add(
            NotificationORM(
                user_id=user_id,
                type="rule_proposal",
                title=f"Automate funding “{candidate['goal_name']}”?",
                message=(
                    f"You've set aside about ${dollars:,.2f} toward "
                    f"“{candidate['goal_name']}” {candidate['period']} "
                    f"{candidate['count']} times. You can turn this into an "
                    "auto-fund rule — it only sets money aside virtually when a "
                    "matching transaction posts, and nothing happens until you "
                    "confirm it."
                ),
                ref=ref,
            )
        )
        created += 1
    if created:
        db.flush()
    summary["offers"] = created
    return summary


def _invalidate_agent(user_id: int) -> None:
    """Evict the user's cached Clerk executor(s) so the next turn re-bakes the
    system prompt with the freshly-written memory fact.

    Uses the LIVE process singleton (``routers.assistant.assistant_service``) —
    its ``AgentConversationCache`` is the in-process cache real requests read, so
    a fresh ``AssistantService()`` here would evict a throwaway cache and leave
    the live prompt stale. Imported lazily (the router pulls in heavy deps) and
    failure-isolated so a cache miss never aborts the nightly job."""
    try:
        from ..routers.assistant import assistant_service

        assistant_service.invalidate_agent(user_id)
    except Exception:  # noqa: BLE001 — a cache eviction failure must never abort the job
        log.exception("invalidate_agent failed after reflection fact: user=%s", user_id)
