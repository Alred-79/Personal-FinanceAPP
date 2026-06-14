"""The Assisted Action Bridge (Pillar 2C).

A *Bridge* is a deduced real-world action: the agent computes the EXACT thing the
user should do in their real bank (transfer $X from A→B, pay $Y to the IRS, set
$Z aside), hands them a frictionless one-tap path to execute it, and the app
reconciles against the next Plaid sync to confirm it actually happened. The
virtual deduction *leads to something real* — but the irreversible bank action
stays with the human; the app only computes, guides, and verifies via the
read-only sync it already has.

Trust model (R2): a user tapping "I did it" sets ``confirmed_done`` — PROVISIONAL.
The source of truth is the sync reconciliation: a Bridge only reaches ``verified``
(and only then mirrors any related virtual earmark) when a MATCHING real
transaction is observed. A stable ``verify_ref`` dedups so the same intent can't
be created — or counted — twice.

Reconciliation shapes (R8) — deliberately NOT ``matching.find_*`` (those relate
two EXISTING internal transactions; a Bridge matches a pending EXTERNAL intent
against freshly-synced rows):
  * ``transfer`` is TWO legs — a debit at ``source_ref`` AND a credit at
    ``dest_ref`` (often different dates, bank-chosen names). Both legs ⇒
    ``verified``; one leg seen ⇒ stay ``acknowledged`` (partial), never verified.
  * single-leg kinds (``bill_payment`` / ``tax_payment`` / ``debt_payment``) match
    ONE outflow at ``source_ref``.
We reuse only the amount/date tolerance PRIMITIVES from ``matching`` (``MatchRow``,
``within_window``), not its top-level pairing functions.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import (
    AssistedAction as AssistedActionORM,
    Goal as GoalORM,
    Notification as NotificationORM,
)
from server.src.services.game.firewall import screen_output
from server.src.services.matching import MatchRow, within_window

log = logging.getLogger(__name__)

# The exact-dollar-amount tolerance: integer cents, EXACT (a transfer posts for
# the amount initiated; we never fuzzy-match money). The date window is wider
# than import dedup's because a real transfer's two legs can post a few days
# apart (initiation vs. settlement at the receiving institution).
_RECONCILE_WINDOW_DAYS = 5
# After this many days with no matching sync, a still-unverified Bridge the user
# marked done earns a gentle nudge ("you marked it done but I don't see it yet").
_NUDGE_AFTER_DAYS = 4

KINDS = ("transfer", "bill_payment", "goal_funding", "tax_payment", "debt_payment")
_SINGLE_LEG_KINDS = ("bill_payment", "tax_payment", "debt_payment", "goal_funding")

# Statuses that are still "open" for reconciliation — we try to verify a Bridge
# the user acknowledged or marked done, but never one already resolved.
_OPEN_FOR_RECONCILE = ("acknowledged", "confirmed_done")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AssistedActionError(ValueError):
    """A Bridge could not be built or transitioned."""


class AssistedActionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── propose ───────────────────────────────────────────────────────────
    def propose(
        self,
        user_id: int,
        *,
        kind: str,
        amount_cents: int,
        rationale: str,
        source_ref: Optional[str] = None,
        dest_ref: Optional[str] = None,
        how: Optional[dict[str, Any]] = None,
        verify_ref: Optional[str] = None,
    ) -> AssistedActionORM:
        """Build a Bridge (deterministic). Dedups by ``verify_ref``.

        ``rationale`` is the deterministic, factual "why" ("$340 short of this
        month's target") and is run through ``screen_output`` — it must never
        become advice or shame (R4). A blocked rationale is replaced with a neutral
        factual fallback rather than rejected, so the Bridge still surfaces.
        """
        if kind not in KINDS:
            raise AssistedActionError(f"unsupported bridge kind: {kind!r}")
        if amount_cents <= 0:
            raise AssistedActionError("amount_cents must be positive")

        # R4: the rationale is data, not advice. Screen it; if it trips the
        # firewall, fall back to a bare factual statement (never the redirect copy,
        # which would read oddly on a Bridge card).
        verdict = screen_output(rationale or "", plain=True)
        safe_rationale = (
            rationale
            if not verdict.blocked
            else "This action keeps your plan on track."
        )

        created = _now_iso()
        verify_ref = verify_ref or self._default_verify_ref(
            user_id, kind, amount_cents, source_ref, dest_ref, created
        )
        # Dedup: an identical un-resolved intent already exists → return it.
        existing = self.db.execute(
            select(AssistedActionORM).where(
                AssistedActionORM.user_id == user_id,
                AssistedActionORM.verify_ref == verify_ref,
                AssistedActionORM.status.in_(
                    ("proposed", "acknowledged", "confirmed_done")
                ),
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        bridge = AssistedActionORM(
            user_id=user_id,
            kind=kind,
            amount_cents=int(amount_cents),
            source_ref=source_ref,
            dest_ref=dest_ref,
            rationale=safe_rationale,
            how_json=json.dumps(how or {}),
            status="proposed",
            settlement_status=None,  # reserved (real-money appendix); NULL in 2C
            verify_ref=verify_ref,
            created_at=created,
        )
        self.db.add(bridge)
        self.db.flush()
        return bridge

    @staticmethod
    def _default_verify_ref(
        user_id: int,
        kind: str,
        amount_cents: int,
        source_ref: Optional[str],
        dest_ref: Optional[str],
        created_iso: Optional[str] = None,
    ) -> str:
        """Stable dedup key for a Bridge.

        Includes the creation DAY so a *recurring* same-amount/same-account intent
        (e.g. a $340 transfer every month) produces a DISTINCT Bridge each day it's
        proposed — without the day, the second occurrence would dedup into the
        still-open first one and be silently swallowed. Same-day re-proposals (a
        double-confirm, a retried tool call) still collapse to one, which is the
        actual replay case we want to dedup.
        """
        day = (created_iso or "")[:10]
        return (
            f"bridge:{user_id}:{kind}:{amount_cents}:"
            f"{source_ref or ''}:{dest_ref or ''}:{day}"
        )

    # ── lifecycle transitions ─────────────────────────────────────────────
    def _own(self, user_id: int, action_id: int) -> AssistedActionORM:
        bridge = self.db.execute(
            select(AssistedActionORM).where(
                AssistedActionORM.id == action_id,
                AssistedActionORM.user_id == user_id,
            )
        ).scalar_one_or_none()
        if bridge is None:
            raise AssistedActionError("Bridge not found")
        return bridge

    def acknowledge(self, user_id: int, action_id: int) -> AssistedActionORM:
        """User opened/started the action (tapped 'Do it in my bank')."""
        bridge = self._own(user_id, action_id)
        if bridge.status == "proposed":
            bridge.status = "acknowledged"
            self.db.flush()
        return bridge

    def mark_done(self, user_id: int, action_id: int) -> AssistedActionORM:
        """User tapped 'I did it'. PROVISIONAL — the sync verifies the truth (R2)."""
        bridge = self._own(user_id, action_id)
        if bridge.status in ("proposed", "acknowledged"):
            bridge.status = "confirmed_done"
            self.db.flush()
        return bridge

    def dismiss(self, user_id: int, action_id: int) -> AssistedActionORM:
        bridge = self._own(user_id, action_id)
        bridge.status = "dismissed"
        bridge.resolved_at = _now_iso()
        self.db.flush()
        return bridge

    def expire(self, user_id: int, action_id: int) -> AssistedActionORM:
        bridge = self._own(user_id, action_id)
        bridge.status = "expired"
        bridge.resolved_at = _now_iso()
        self.db.flush()
        return bridge

    def list(self, user_id: int, *, open_only: bool = False) -> list[AssistedActionORM]:
        q = select(AssistedActionORM).where(AssistedActionORM.user_id == user_id)
        if open_only:
            q = q.where(
                AssistedActionORM.status.in_(
                    ("proposed", "acknowledged", "confirmed_done")
                )
            )
        return list(
            self.db.execute(q.order_by(AssistedActionORM.id.desc())).scalars().all()
        )

    # ── reconcile against freshly-synced transactions ─────────────────────
    def reconcile(
        self,
        user_id: int,
        synced_txns: Iterable[dict[str, Any]],
        *,
        window_days: int = _RECONCILE_WINDOW_DAYS,
        today: Optional[date] = None,
    ) -> list[AssistedActionORM]:
        """Match open Bridges against newly-synced bank rows; verify the matches.

        *synced_txns* are dicts: ``{amount_cents (SIGNED: +in/-out), account_id,
        date, title}``. For each open Bridge:
          * ``transfer``  → require BOTH a debit at ``source_ref`` and a credit at
            ``dest_ref`` of the exact magnitude within the window. Both ⇒
            ``verified``; one ⇒ stay ``acknowledged`` (partial; never verified).
          * single-leg    → require one outflow of the magnitude at ``source_ref``.
        On ``verified`` we mirror any related virtual earmark (``how_json.goal_id``)
        to reflect the now-real money, then mark resolved. A Bridge the user marked
        done that stays unmatched past ``_NUDGE_AFTER_DAYS`` gets one gentle nudge.

        Returns the Bridges whose status changed to ``verified``.
        """
        rows = [self._to_match_row(t) for t in synced_txns]
        rows = [r for r in rows if r is not None]
        open_bridges = self.list(user_id, open_only=True)
        verified: list[AssistedActionORM] = []

        for bridge in open_bridges:
            if bridge.status not in _OPEN_FOR_RECONCILE:
                continue  # 'proposed' (untouched) isn't reconciled until acted on
            if bridge.kind == "transfer":
                matched = self._match_transfer_legs(bridge, rows, window_days)
            else:
                matched = self._match_single_leg(bridge, rows, window_days)
            if matched:
                self._verify(bridge)
                verified.append(bridge)
            else:
                self._maybe_nudge(bridge, today=today)
        return verified

    @staticmethod
    def _to_match_row(t: dict[str, Any]) -> Optional[MatchRow]:
        try:
            amount_cents = int(t["amount_cents"])
        except (KeyError, TypeError, ValueError):
            return None
        return MatchRow(
            ref=t.get("ref") or t.get("id"),
            title=str(t.get("title") or ""),
            amount_cents=amount_cents,  # SIGNED: +in / -out
            date=t.get("date") or "",
            account_id=t.get("account_id"),
        )

    def _match_transfer_legs(
        self, bridge: AssistedActionORM, rows: list[MatchRow], window_days: int
    ) -> bool:
        """A transfer is TWO legs: a debit at source + a credit at dest, same
        magnitude, within the window. Purpose-built (R8) — ``find_pairings`` can't
        model one intent → two legs across two accounts.

        ``source_ref``/``dest_ref`` are account ids (as strings) for an internal
        transfer. If either side isn't an internal account (external label), we
        can't see that leg via Plaid, so the transfer can't be two-leg verified —
        it falls through to single-leg semantics handled by the caller's else
        branch only for the single-leg kinds, so an external-dest transfer simply
        won't verify here (stays acknowledged), which is correct.
        """
        magnitude = bridge.amount_cents
        src = _as_account_id(bridge.source_ref)
        dst = _as_account_id(bridge.dest_ref)
        if src is None or dst is None:
            return False
        anchor = self._anchor_row(bridge)
        debit = any(
            r.account_id == src
            and r.amount_cents == -magnitude  # money out of source
            and self._within(anchor, r, window_days)
            for r in rows
        )
        credit = any(
            r.account_id == dst
            and r.amount_cents == magnitude  # money into dest
            and self._within(anchor, r, window_days)
            for r in rows
        )
        # Both legs required. One leg only → partial; caller keeps it acknowledged.
        return debit and credit

    def _match_single_leg(
        self, bridge: AssistedActionORM, rows: list[MatchRow], window_days: int
    ) -> bool:
        """One outflow of the magnitude at ``source_ref`` (bill/tax/debt/goal).

        ``source_ref`` is the paying account. The destination is external (the IRS,
        a biller) so there's no second internal leg to see — one debit suffices.
        """
        magnitude = bridge.amount_cents
        src = _as_account_id(bridge.source_ref)
        anchor = self._anchor_row(bridge)
        for r in rows:
            if r.amount_cents != -magnitude:
                continue
            if src is not None and r.account_id != src:
                continue
            if self._within(anchor, r, window_days):
                return True
        return False

    def _anchor_row(self, bridge: AssistedActionORM) -> MatchRow:
        """A synthetic MatchRow at the Bridge's own date, to reuse ``within_window``
        for the date-tolerance comparison."""
        return MatchRow(
            ref=bridge.id,
            title="",
            amount_cents=bridge.amount_cents,
            date=(bridge.created_at or "")[:10],
        )

    @staticmethod
    def _within(anchor: MatchRow, row: MatchRow, window_days: int) -> bool:
        # Fail CLOSED on a missing anchor date, mirroring ``matching.within_window``
        # (a row with no parseable date never matches): a Bridge with no
        # ``created_at`` must not verify against a same-amount row from *any* date —
        # that would silently confirm an unrelated transfer. ``propose`` always
        # stamps ``created_at``, so this only guards a malformed/hand-built row.
        if not anchor.date:
            return False
        return within_window(anchor, row, window_days)

    def _verify(self, bridge: AssistedActionORM) -> None:
        """Transition a matched Bridge to ``verified`` and mirror its earmark.

        Only a VERIFIED Bridge funds the related virtual earmark — provisional
        ``confirmed_done`` never does (R2). ``how_json.goal_id`` links a Bridge to a
        goal earmark; if present and not already mirrored, add the amount to
        ``Goal.progress`` to reflect the now-real money exactly once.
        """
        bridge.status = "verified"
        bridge.resolved_at = _now_iso()
        how = _loads(bridge.how_json)
        goal_id = how.get("goal_id")
        if goal_id is not None:
            goal = self.db.execute(
                select(GoalORM).where(
                    GoalORM.id == goal_id, GoalORM.user_id == bridge.user_id
                )
            ).scalar_one_or_none()
            if goal is not None and not how.get("_mirrored"):
                goal.progress = (goal.progress or 0) + bridge.amount_cents
                if goal.progress >= goal.amount:
                    goal.completed = 1
                how["_mirrored"] = True
                bridge.how_json = json.dumps(how)
        self.db.flush()

    def _maybe_nudge(
        self, bridge: AssistedActionORM, *, today: Optional[date] = None
    ) -> None:
        """A 'confirmed_done' Bridge unseen in the sync after N days → one nudge.

        Idempotent: the notification ``ref`` is keyed to the Bridge so re-running
        reconcile doesn't stack duplicate nudges.
        """
        if bridge.status != "confirmed_done" or not bridge.created_at:
            return
        created = _parse_date(bridge.created_at)
        if created is None:
            return
        ref_day = today or datetime.now(timezone.utc).date()
        if (ref_day - created).days < _NUDGE_AFTER_DAYS:
            return
        ref = f"bridge_nudge:{bridge.id}"
        exists = self.db.execute(
            select(NotificationORM.id).where(
                NotificationORM.user_id == bridge.user_id,
                NotificationORM.ref == ref,
            )
        ).scalar_one_or_none()
        if exists is not None:
            return
        dollars = bridge.amount_cents / 100
        self.db.add(
            NotificationORM(
                user_id=bridge.user_id,
                type="bridge_nudge",
                title="Did that transfer go through?",
                message=(
                    f"You marked the ${dollars:,.2f} {bridge.kind.replace('_', ' ')} "
                    "as done, but I don't see it in your synced transactions yet."
                ),
                ref=ref,
            )
        )
        self.db.flush()


def _as_account_id(ref: Optional[str]) -> Optional[int]:
    """An internal account leg is an integer-valued ``source_ref``/``dest_ref``.

    External labels ("irs.gov/payments", "your bank") return None — they have no
    Plaid-visible leg, so they never participate in a two-leg match.
    """
    if ref is None:
        return None
    try:
        return int(ref)
    except (TypeError, ValueError):
        return None


def _loads(text: Optional[str]) -> dict[str, Any]:
    try:
        out = json.loads(text) if text else {}
        return out if isinstance(out, dict) else {}
    except (TypeError, ValueError):
        return {}


def _parse_date(value: str) -> Optional[date]:
    try:
        return datetime.fromisoformat(value).date()
    except (TypeError, ValueError):
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None
