"""W6 — Honest subscription cancellation (detect → offer → absence-verify).

The most-complained automation in this category "cancels" a subscription and then
keeps a cut of the money it claims to save. This inverts that: we DETECT a likely-
forgotten or silently-hiked subscription from the shipped F2 lifecycle, OFFER one
honest, dismissible one-tap cancel path (the provider's own cancel URL / steps),
and VERIFY it actually stopped by the *absence* of the next expected charge — and
we NEVER move money, never auto-cancel, and (asserted in tests) carry NO fee field
anywhere on this path. The offer PROPOSES; tapping it mints a propose-only Bridge
(``kind="subscription_cancel"``) through the existing action-token flow (C2). The
user does the cancelling in their real account; the app only guides and confirms.

Two halves, both per-user and both run from the nightly job (B1 binds the RLS
tenant before either touches user data):

1. **Detect → offer.** Over ``MerchantLifecycle`` rows, flag candidates —
   ``status in ("lapsing","dormant")`` with a low ``probability_alive`` (a likely-
   forgotten "zombie"), OR a positive ``price_change_pct`` (a silent price hike).
   Fire ONE idempotent ``Notification(type="subscription_cancel",
   ref="sub_cancel:{user}:{merchant}:{period}")`` per candidate. ``period`` is the
   offer cycle (``YYYY-MM`` of the run), so a later re-subscribe starts a FRESH
   detection cycle rather than re-opening a resolved one.

2. **Absence-verify.** For each OPEN ``subscription_cancel`` bridge, call
   ``assisted_action_service.verify_cancellation(bridge, as_of)`` — which marks it
   ``verified`` only after a full missed cadence + grace with no matching charge at
   the normalized merchant key, keeps it open if a charge reappears, and expires it
   (with a nudge) if it dangles past the cadence-scaled cap (the annual case).

RLS (guardrail B1): functions take an explicit ``user_id`` and assume the caller
(``scheduler.job_subscription_actions``) has already bound the tenant or runs under
the BYPASSRLS scheduler role.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    AssistedAction as AssistedActionORM,
    MerchantLifecycle as MerchantLifecycleORM,
    Notification as NotificationORM,
)
from ..settings import settings
from .assisted_action_service import AssistedActionService
from .game.firewall import screen_output

log = logging.getLogger(__name__)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _period(now: date) -> str:
    return f"{now.year}-{now.month:02d}"


def is_candidate(
    row: MerchantLifecycleORM, *, max_probability_alive: float
) -> bool:
    """True if a lifecycle row is a zombie / price-creep cancel candidate.

    Two honest signals (per the W6 spec):
      * **Forgotten / zombie:** ``status`` has fallen to ``lapsing`` or ``dormant``
        AND ``probability_alive`` is below ``max_probability_alive`` — it billed
        regularly then went quiet, the classic forgotten sub.
      * **Silent hike:** ``price_change_pct`` is positive — the price crept up.

    A healthy, still-active monthly with no price rise is NOT a candidate (the F2
    backtest's "flags zombies not healthy monthlies" requirement)."""
    forgotten = (
        row.status in ("lapsing", "dormant")
        and row.probability_alive < max_probability_alive
    )
    hiked = (row.price_change_pct or 0.0) > 0.0
    return bool(forgotten or hiked)


def detect_candidates(
    db: Session, user_id: int, *, max_probability_alive: float
) -> list[MerchantLifecycleORM]:
    """The user's lifecycle rows that qualify for one honest cancel offer. Pure
    read; the caller mints ≤1 idempotent offer per row."""
    rows = (
        db.execute(
            select(MerchantLifecycleORM).where(
                MerchantLifecycleORM.user_id == user_id
            )
        )
        .scalars()
        .all()
    )
    return [r for r in rows if is_candidate(r, max_probability_alive=max_probability_alive)]


def _offer_ref(user_id: int, merchant: str, period: str) -> str:
    """Stable dedup key. Includes the offer ``period`` (``YYYY-MM``) so a *new*
    cycle (e.g. the user re-subscribed months later and forgot again) gets a fresh
    offer, while a same-month re-run is a no-op."""
    return f"sub_cancel:{user_id}:{merchant}:{period}"


def _offer_exists(db: Session, user_id: int, ref: str) -> bool:
    """Read-or-unread dedup AND dismissal suppression: any notification with this
    ref (the user may have already seen and dismissed it) blocks a re-offer."""
    return (
        db.execute(
            select(NotificationORM.id).where(
                NotificationORM.user_id == user_id,
                NotificationORM.ref == ref,
            )
        ).first()
        is not None
    )


def _open_cancel_bridge_for(
    db: Session, user_id: int, merchant: str
) -> Optional[AssistedActionORM]:
    """An already-open cancel bridge for this merchant (so we don't double-offer
    once the user has tapped through to a bridge for it)."""
    rows = (
        db.execute(
            select(AssistedActionORM).where(
                AssistedActionORM.user_id == user_id,
                AssistedActionORM.kind == "subscription_cancel",
                AssistedActionORM.status.in_(
                    ("proposed", "acknowledged", "confirmed_done")
                ),
            )
        )
        .scalars()
        .all()
    )
    for b in rows:
        how = _loads(b.how_json)
        if (how.get("merchant") or "") == merchant:
            return b
    return None


def _loads(text: Optional[str]) -> dict[str, Any]:
    try:
        out = json.loads(text) if text else {}
        return out if isinstance(out, dict) else {}
    except (TypeError, ValueError):
        return {}


def offer_how(row: MerchantLifecycleORM) -> dict[str, Any]:
    """The ``how_json`` affordance carried into the cancel Bridge on tap.

    Carries the cancellation affordance (a provider cancel URL / steps / deep link)
    PLUS the absence-verification anchors (merchant key, cadence, expected next
    date, last amount) that ``verify_cancellation`` reads. There is intentionally
    NO fee/savings field — we never claim or skim a saved amount."""
    return {
        "merchant": row.merchant,
        "title": row.title or row.merchant,
        "cadence": row.cadence,
        "expected_next_date": row.expected_next_date,
        "last_amount_cents": int(row.last_amount or 0),
        # Provider affordance — a deterministic, factual cancel path. We don't ship
        # a per-merchant directory here; a generic, honest instruction is the safe
        # default the UI can enrich. (No fee, no upsell.)
        "cancel_steps": (
            "Open the provider's account or billing settings and cancel the "
            "subscription directly. I'll confirm it stopped on your next sync."
        ),
        "cancel_url": None,
    }


def _offer_message(row: MerchantLifecycleORM) -> tuple[str, str]:
    """A FACTUAL, non-directive (title, message) for the offer notification.

    Deliberately states the observation (the charge, the signal) and that a cancel
    option exists — NOT an imperative instruction (which trips the output firewall's
    imperative+money heuristic and, more importantly, would read as advice). The
    actual cancel affordance lives in ``how_json`` on the tapped Bridge. No
    fee/skim language anywhere (the no-fee guard greps the copy)."""
    name = row.title or row.merchant
    dollars = (row.last_amount or 0) / 100
    if (row.price_change_pct or 0) > 0:
        pct = round((row.price_change_pct or 0) * 100)
        title = f"{name} raised its price"
        message = (
            f"{name}'s charge rose about {pct}% to ${dollars:,.2f}. A one-tap "
            "cancel option is available here, and it only verifies the charge "
            "stopped on your next sync — no money is moved."
        )
    else:
        title = f"Forgotten subscription: {name}?"
        message = (
            f"{name} appears to be a forgotten subscription, last charging "
            f"${dollars:,.2f}. A one-tap cancel option is available here, and it "
            "only verifies the charge stopped on your next sync — no money is moved."
        )
    return title, message


def run_for_user(
    db: Session,
    user_id: int,
    *,
    now: date,
    max_probability_alive: Optional[float] = None,
) -> dict[str, Any]:
    """Detect→offer + absence-verify for ONE user. Assumes the caller has bound the
    RLS tenant (B1). Returns ``{offers, verified, expired}``.

    Propose-only (B2): an offer is a Notification; the cancel Bridge is minted only
    when the user TAPS (via the action-token flow, C2). Nothing here cancels a
    subscription or moves money."""
    if max_probability_alive is None:
        max_probability_alive = settings.subscription_forgotten_max_probability

    period = _period(now)
    offers = 0

    # ── detect → offer ───────────────────────────────────────────────────
    for row in detect_candidates(db, user_id, max_probability_alive=max_probability_alive):
        # Already an open bridge for this merchant → the user is mid-flow; don't
        # also stack a fresh offer notification.
        if _open_cancel_bridge_for(db, user_id, row.merchant) is not None:
            continue
        ref = _offer_ref(user_id, row.merchant, period)
        if _offer_exists(db, user_id, ref):
            continue
        title, message = _offer_message(row)
        # The copy is factual data, not advice/shame — screen it like any output.
        if screen_output(message, plain=True).blocked:
            continue
        db.add(
            NotificationORM(
                user_id=user_id,
                type="subscription_cancel",
                title=title,
                message=message,
                ref=ref,
            )
        )
        offers += 1

    # ── absence-verify open cancel bridges ───────────────────────────────
    svc = AssistedActionService(db)
    verified = 0
    expired = 0
    open_bridges = (
        db.execute(
            select(AssistedActionORM).where(
                AssistedActionORM.user_id == user_id,
                AssistedActionORM.kind == "subscription_cancel",
                AssistedActionORM.status.in_(
                    ("proposed", "acknowledged", "confirmed_done")
                ),
            )
        )
        .scalars()
        .all()
    )
    for bridge in open_bridges:
        outcome = svc.verify_cancellation(bridge, as_of=now)
        if outcome == "verified":
            verified += 1
        elif outcome == "expired":
            expired += 1

    if offers or verified or expired:
        db.flush()
    return {"offers": offers, "verified": verified, "expired": expired}


def propose_cancel_bridge(
    db: Session, user_id: int, merchant: str
) -> AssistedActionORM:
    """Mint the propose-only cancel Bridge for a tapped offer (the C2 'on tap'
    path). Builds an ``AssistedAction(kind="subscription_cancel")`` carrying the
    cancel affordance + absence-verify anchors in ``how_json`` — it never cancels
    anything and never moves money. Idempotent via the service's ``verify_ref``.

    Raises if there's no current lifecycle row for the merchant (the offer is
    stale)."""
    row = db.execute(
        select(MerchantLifecycleORM).where(
            MerchantLifecycleORM.user_id == user_id,
            MerchantLifecycleORM.merchant == merchant,
        )
    ).scalar_one_or_none()
    if row is None:
        from .assisted_action_service import AssistedActionError

        raise AssistedActionError("no lifecycle row for this merchant; offer is stale")

    name = row.title or row.merchant
    svc = AssistedActionService(db)
    return svc.propose(
        user_id,
        kind="subscription_cancel",
        # amount is the last charge (display only — NEVER banked / no fee).
        amount_cents=max(int(row.last_amount or 0), 1),
        rationale=f"Cancel {name} — verified by the absence of the next charge.",
        source_ref=None,
        dest_ref=None,
        how=offer_how(row),
        # Stable per-merchant verify key (no day suffix: only one open cancel
        # bridge per merchant at a time — a later re-subscribe is a new cycle once
        # this one resolves).
        verify_ref=f"sub_cancel_bridge:{user_id}:{merchant}",
    )
