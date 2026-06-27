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
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.src.db.models import (
    AssistedAction as AssistedActionORM,
    Goal as GoalORM,
    Notification as NotificationORM,
    UsedActionToken as UsedActionTokenORM,
)
from server.src.services import action_tokens
from server.src.services.game.firewall import screen_output
from server.src.services.matching import MatchRow, within_window
from server.src.services.rails.base import (
    FundingResolver,
    ORIGINABLE_KINDS,
    RailAdapter,
    RailError,
    rail_for_kind,
)
from server.src.settings import settings

log = logging.getLogger(__name__)

# Phase 2a–2b confirmation-token action label. A fresh, single-use, short-TTL
# token bound to (action_id, amount_cents) is minted server-side when the user
# taps "Send it" on a specific Bridge and consumed exactly once by ``execute()``.
# It reuses the assistant-action token family (HKDF-derived key + aud + one-use
# jti) so it can never be substituted for a session/MCP/confirm token.
EXECUTE_TOKEN_ACTION = "execute_assisted_action"

# Statuses from which an originable Bridge may be executed: the user has engaged
# it (acknowledged / marked done) but it isn't resolved. Not ``proposed``.
_EXECUTABLE_STATUSES = ("acknowledged", "confirmed_done")
# settlement_status values that mean an origination already happened (idempotency).
_ALREADY_ORIGINATED = ("submitted", "pending", "settled", "returned", "failed")

# The exact-dollar-amount tolerance: integer cents, EXACT (a transfer posts for
# the amount initiated; we never fuzzy-match money). The date window is wider
# than import dedup's because a real transfer's two legs can post a few days
# apart (initiation vs. settlement at the receiving institution).
_RECONCILE_WINDOW_DAYS = 5
# After this many days with no matching sync, a still-unverified Bridge the user
# marked done earns a gentle nudge ("you marked it done but I don't see it yet").
_NUDGE_AFTER_DAYS = 4

KINDS = (
    "transfer",
    "bill_payment",
    "goal_funding",
    "tax_payment",
    "debt_payment",
    # W6 — an honest subscription-cancel offer. It PROPOSES (provider cancel URL /
    # steps live in ``how_json``); it never acts and never moves money. Unlike the
    # money kinds it is verified by the ABSENCE of the next expected charge, so it
    # is reconciled by ``verify_cancellation`` (in the nightly job), NOT by the
    # appearing-transaction ``reconcile`` (C6). There is NO fee field anywhere on
    # this path — we never claim or skim a "saved" amount.
    "subscription_cancel",
)
_SINGLE_LEG_KINDS = ("bill_payment", "tax_payment", "debt_payment", "goal_funding")

# W6 — cadence (in days) used to size the absence-verification horizon and the
# open-bridge expiry cap. Mirrors ``recurring_service._RECURRENCE_DAYS`` /
# ``subscription_service._CADENCE_WINDOWS`` so the two features agree on calendar
# math; an unknown/None cadence falls back to a conservative monthly horizon.
_CADENCE_DAYS = {
    "weekly": 7,
    "bi-weekly": 14,
    "monthly": 30,
    "quarterly": 91,
    "annually": 365,
}
_DEFAULT_CADENCE_DAYS = 30
# After the expected next charge would have posted, we wait this many extra days
# (banks post a renewal a few days late; a merchant may bill on a slightly
# different day) before calling an absent charge a confirmed cancellation. One
# FULL missed cadence + this grace is the bar — a single early/one-cycle gap must
# NOT verify (edge case: false "cancelled").
_CANCEL_GRACE_DAYS = 7
# A cancel bridge can't hang open forever. An ABSOLUTE day cap on how long it
# stays open: for short cadences this sits AFTER the verify horizon (so absence
# verification wins first); for a long (annual) cadence the horizon is itself ~a
# year out, so this cap is reached FIRST — we then EXPIRE with a nudge rather than
# leave a cancel offer dangling for a year. Also bounds the reappearing-charge case
# (a sub that keeps renewing under a fuzzy key never verifies, but mustn't hang).
_CANCEL_MAX_OPEN_DAYS = 120

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

    # ── execute(): originate a real transfer at a rail (Phase 2a, SANDBOX) ──
    def execute(
        self,
        user_id: int,
        action_id: int,
        *,
        rail: RailAdapter,
        confirmation_token: str,
        funding: FundingResolver,
        today: Optional[date] = None,
    ) -> AssistedActionORM:
        """Originate the real-world money movement for an eligible Bridge.

        SANDBOX ONLY and dark behind ``rail_origination_enabled`` — see
        docs/PHASE2A-SANDBOX-IMPLEMENTATION.md and the parent design §4. Idempotent
        and guard-railed: every guard below must pass before any rail call. Sets
        ``settlement_status='submitted'`` and records the rail reference; it NEVER
        sets ``status='verified'`` and NEVER mirrors the earmark — mirroring stays
        with settlement (``apply_settlement``) / ``reconcile``, reusing ``_verify``.

        Replay-safe: a second ``execute()`` on an already-originated Bridge returns
        it unchanged (no exception, no second rail call). On ``RailError`` from the
        rail the Bridge is left exactly as it was (``settlement_status`` stays None)
        with the error recorded, so the manual fallback remains available.
        """
        # Guard 1 — master flag (belt-and-suspenders; the endpoint also 404s off).
        if not settings.rail_origination_enabled:
            raise RailError("rail origination is disabled")
        # Guard 2 — ownership.
        bridge = self._own(user_id, action_id)
        # Guard 3 — kind eligible (pure mapping; raises for a non-originable kind).
        if bridge.kind not in ORIGINABLE_KINDS:
            raise RailError(f"kind {bridge.kind!r} is not originable")
        rail_name = rail_for_kind(bridge.kind)
        # Guard 4 — status gate: the user must have engaged it, and it isn't resolved.
        if bridge.status not in _EXECUTABLE_STATUSES:
            raise RailError(
                f"bridge status {bridge.status!r} is not executable"
            )
        # Guard 5 — idempotency: an origination already happened → return unchanged.
        if bridge.settlement_status is not None:
            if bridge.settlement_status in _ALREADY_ORIGINATED:
                return bridge
            raise RailError(
                f"unexpected settlement_status {bridge.settlement_status!r}"
            )
        # Guard 6 — fresh, single-use human confirmation bound to this id+amount.
        self._consume_confirmation_token(
            user_id, action_id, bridge.amount_cents, confirmation_token
        )
        # Guard 7 — caps: per-transaction hard ceiling and rolling daily total.
        # ``day`` is the injected (deterministic) origination day, reused below as
        # the stamp so the rolling cap measures originations on the same calendar.
        day = today or datetime.now(timezone.utc).date()
        self._check_caps(user_id, bridge, day=day)
        # Guard 8 — funding resolution. Until 2c the resolver raises for every
        # account, so execute() correctly falls back to manual (RailError).
        source = funding.resolve_source(rail_name, bridge.source_ref)
        dest = funding.resolve_dest(rail_name, bridge.dest_ref)
        # Guard 9 — originate. The Bridge's stable verify_ref is the rail
        # idempotency key, so a retry can't double-send at the rail either.
        idem = bridge.verify_ref or self._default_verify_ref(
            user_id, bridge.kind, bridge.amount_cents,
            bridge.source_ref, bridge.dest_ref, bridge.created_at,
        )
        memo = _loads(bridge.how_json).get("memo") or bridge.kind.replace("_", " ")
        try:
            result = rail.originate(
                amount_cents=bridge.amount_cents,
                source=source,
                dest=dest,
                idempotency_key=idem,
                memo=memo,
            )
        except RailError as exc:
            # Leave settlement_status=None (not advanced); record the failure.
            bridge.settlement_detail_json = json.dumps(
                {"error": str(exc), "at": _now_iso()}
            )
            self.db.flush()
            log.warning(
                "rail origination failed: user=%s action=%s rail=%s amount=%s err=%s",
                user_id, action_id, rail_name, bridge.amount_cents, exc,
            )
            raise
        # Guard 10 — persist the submitted origination. ``originated_on`` is the
        # deterministic calendar day the rolling daily cap counts against (the
        # injected ``today`` when given); ``originated_at`` is the audit timestamp.
        bridge.settlement_status = result.settlement_status
        bridge.rail = result.rail
        bridge.rail_ref = result.rail_ref
        bridge.settlement_detail_json = json.dumps(
            {
                "originated_at": _now_iso(),
                "originated_on": day.isoformat(),
                "outcome": result.settlement_status,
            }
        )
        self.db.flush()
        # Guard 11 — append-only audit line (who / when / amount / rail / ref).
        log.info(
            "rail origination submitted: user=%s action=%s rail=%s ref=%s amount=%s",
            user_id, action_id, result.rail, result.rail_ref, bridge.amount_cents,
        )
        return bridge

    def _consume_confirmation_token(
        self, user_id: int, action_id: int, amount_cents: int, token: str
    ) -> None:
        """Validate + one-use-consume the execute confirmation token (guard 6).

        Decodes via the assistant-action token family (HKDF key + aud + TTL), then
        requires the token's action label and its bound ``(action_id, amount_cents)``
        to match THIS Bridge, and claims its one-use ``jti`` so a replay is rejected.
        """
        try:
            payload = action_tokens.decode_token(token)
        except action_tokens.ActionTokenError as exc:
            raise RailError(f"invalid confirmation token: {exc}")
        if payload.get("action") != EXECUTE_TOKEN_ACTION:
            raise RailError("not an execute-confirmation token")
        if int(payload.get("uid", -1)) != int(user_id):
            raise RailError("confirmation token belongs to another user")
        params = payload.get("params") or {}
        if int(params.get("action_id", -1)) != int(action_id):
            raise RailError("confirmation token is for a different action")
        if int(params.get("amount_cents", -1)) != int(amount_cents):
            raise RailError("confirmation token amount does not match")
        if not self._reserve_jti(user_id, payload.get("jti")):
            raise RailError("confirmation token already used")

    def _reserve_jti(self, user_id: int, jti: Optional[str]) -> bool:
        """Claim *jti* once (replay guard). False if missing or already spent.

        The DB UNIQUE constraint on ``jti`` is the authority across workers/hosts,
        mirroring ``ActionService.reserve_jti`` (kept local to avoid an import
        cycle with the assistant layer)."""
        if not jti:
            return False
        self.db.add(UsedActionTokenORM(jti=jti, user_id=user_id))
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            return False
        return True

    def _check_caps(
        self, user_id: int, bridge: AssistedActionORM, *, day: date
    ) -> None:
        """Guard 7: per-transaction ceiling + rolling daily total (sandbox caps)."""
        amount = bridge.amount_cents
        if amount > settings.rail_per_txn_cap_cents:
            raise RailError(
                f"amount {amount} exceeds per-transaction cap "
                f"{settings.rail_per_txn_cap_cents}"
            )
        already = self._originated_on_cents(user_id, day, exclude_id=bridge.id)
        if already + amount > settings.rail_daily_cap_cents:
            raise RailError(
                f"daily origination cap exceeded: {already}+{amount} > "
                f"{settings.rail_daily_cap_cents}"
            )

    def _originated_on_cents(
        self, user_id: int, day: date, *, exclude_id: Optional[int] = None
    ) -> int:
        """Sum the cents this user has already originated on *day* (rolling cap).

        Counts every Bridge with a rail set whose recorded ``originated_on`` falls
        on *day* — a returned/failed origination still consumed the day's velocity,
        so it counts (a conservative cap)."""
        rows = self.db.execute(
            select(AssistedActionORM).where(
                AssistedActionORM.user_id == user_id,
                AssistedActionORM.rail.is_not(None),
            )
        ).scalars().all()
        day_iso = day.isoformat()[:10]
        total = 0
        for r in rows:
            if exclude_id is not None and r.id == exclude_id:
                continue
            detail = _loads(r.settlement_detail_json)
            on = (detail.get("originated_on") or "")[:10]
            if on == day_iso:
                total += r.amount_cents
        return total

    # ── apply_settlement(): drive settlement from a verified webhook (2b) ───
    def apply_settlement(
        self, rail: str, rail_ref: str, event: str, *, event_id: Optional[str] = None
    ) -> Optional[AssistedActionORM]:
        """Drive ``settlement_status`` from a verified rail webhook (parent §4.4).

        ``event ∈ {settled, failed, returned}``. Looks the Bridge up by
        ``(rail, rail_ref)``; idempotent per ``(rail_ref, event)`` (a repeat of the
        same terminal event is a no-op); an unknown ref is ignored (returns None).

          * ``settled``  → ``settlement_status='settled'`` + ``_verify`` (mirrors the
            earmark exactly once via the existing ``_mirrored`` guard).
          * ``failed``   → ``settlement_status='failed'``; nothing mirrored, nothing
            to reverse; the Bridge is actionable again (manual fallback).
          * ``returned`` → ``settlement_status='returned'``; if the earmark was
            mirrored, subtract the amount back out of ``Goal.progress`` and clear the
            flag; record the R-code.

        Convergence with Plaid ``reconcile()``: whichever resolves the Bridge first
        wins; the later one is a no-op (both reach ``verified`` exactly once).
        """
        bridge = self.db.execute(
            select(AssistedActionORM).where(
                AssistedActionORM.rail == rail,
                AssistedActionORM.rail_ref == rail_ref,
            )
        ).scalar_one_or_none()
        if bridge is None:
            return None  # unknown ref — ignore

        # Event-id dedup: a webhook may be redelivered. If we've already recorded
        # this exact provider event id on the Bridge, it's a replay → no-op.
        if event_id is not None and event_id in self._recorded_event_ids(bridge):
            return bridge

        if event == "settled":
            if bridge.settlement_status == "settled":
                return bridge  # idempotent replay
            bridge.settlement_status = "settled"
            self._record_settlement_event(bridge, event, event_id)
            # _verify is idempotent (the _mirrored flag guards a double mirror), so
            # if reconcile already verified+mirrored, this won't double-count.
            if bridge.status != "verified":
                self._verify(bridge)
            else:
                self.db.flush()
            return bridge

        if event == "failed":
            if bridge.settlement_status == "failed":
                return bridge
            bridge.settlement_status = "failed"
            self._record_settlement_event(bridge, event, event_id)
            self.db.flush()
            return bridge

        if event == "returned":
            if bridge.settlement_status == "returned":
                return bridge
            bridge.settlement_status = "returned"
            self._reverse_mirror_if_needed(bridge)
            self._record_settlement_event(bridge, event, event_id)
            self.db.flush()
            return bridge

        raise RailError(f"unknown settlement event: {event!r}")

    @staticmethod
    def _recorded_event_ids(bridge: AssistedActionORM) -> set[str]:
        detail = _loads(bridge.settlement_detail_json)
        events = detail.get("events")
        if not isinstance(events, list):
            return set()
        return {
            str(e["event_id"])
            for e in events
            if isinstance(e, dict) and e.get("event_id") is not None
        }

    def _reverse_mirror_if_needed(self, bridge: AssistedActionORM) -> None:
        """On a ``returned`` ACH, undo a mirrored earmark to the cent (parent §4.4).

        Only reverses when ``how['_mirrored']`` is set (a settled webhook or
        reconcile actually funded the goal); clears the flag so it can't reverse
        twice. ``Goal.progress`` never goes negative."""
        how = _loads(bridge.how_json)
        if not how.get("_mirrored"):
            return
        goal_id = how.get("goal_id")
        if goal_id is not None:
            goal = self.db.execute(
                select(GoalORM).where(
                    GoalORM.id == goal_id, GoalORM.user_id == bridge.user_id
                )
            ).scalar_one_or_none()
            if goal is not None:
                goal.progress = max(0, (goal.progress or 0) - bridge.amount_cents)
                if goal.progress < goal.amount:
                    goal.completed = 0
        how["_mirrored"] = False
        bridge.how_json = json.dumps(how)

    @staticmethod
    def _record_settlement_event(
        bridge: AssistedActionORM, event: str, event_id: Optional[str] = None
    ) -> None:
        """Append the settlement event (+ id / R-code) to ``settlement_detail_json``."""
        detail = _loads(bridge.settlement_detail_json)
        events = detail.get("events")
        if not isinstance(events, list):
            events = []
        events.append({"event": event, "event_id": event_id, "at": _now_iso()})
        detail["events"] = events
        detail["last_event"] = event
        bridge.settlement_detail_json = json.dumps(detail)

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


    # ── W6: absence-based verification of a subscription cancellation ─────
    def verify_cancellation(
        self,
        bridge: AssistedActionORM,
        as_of: date,
    ) -> str:
        """Resolve ONE open ``subscription_cancel`` bridge by the ABSENCE of the
        next expected charge — the inverse of C6's appearing-transaction match.

        A cancellation is only *knowable over time*: we can never prove a charge
        won't come, only observe that a full cadence + grace has passed with no
        matching charge at the merchant's NORMALIZED key. So:

          * If any charge at the normalized merchant key has posted AFTER the offer
            (the user kept the sub, or a renewal slipped through under a slightly
            different label/amount), the cancellation did NOT take → stay open
            (``unverified``). This is the false-"cancelled" guard.
          * Else, once ``as_of`` is at/after ``expected_next_date + grace`` (one
            full missed cadence), mark ``verified`` — no fee, no money moved.
          * Else, if the bridge has hung open longer than the cadence-scaled cap
            (``_CANCEL_MAX_CADENCES_OPEN`` cadences past the offer) without ever
            reaching its verify horizon — the annual-cadence "dangling forever"
            case — ``expire`` it with a gentle nudge instead of leaving it open.
          * Else it is simply too early → ``pending``.

        Returns the resulting state label: ``"verified" | "expired" | "pending" |
        "unverified" | "skipped"``. Caller drives ``as_of`` explicitly (no
        ``Date.now()``); the job binds the RLS tenant before calling this.
        """
        if bridge.kind != "subscription_cancel":
            return "skipped"
        if bridge.status not in _OPEN_FOR_RECONCILE and bridge.status != "proposed":
            return "skipped"

        how = _loads(bridge.how_json)
        merchant_key = (how.get("merchant") or "").strip().lower()
        offered = _parse_date(bridge.created_at)
        cadence = how.get("cadence")
        cadence_days = _CADENCE_DAYS.get(cadence or "", _DEFAULT_CADENCE_DAYS)

        # The verify horizon: the merchant's own ``expected_next_date`` when known
        # (it already encodes the cadence), else offer + one cadence. Plus grace.
        expected_next = _parse_date(how.get("expected_next_date") or "")
        if expected_next is None and offered is not None:
            expected_next = offered + timedelta(days=cadence_days)
        if expected_next is None:
            return "pending"  # malformed bridge — never silently verify
        horizon = expected_next + timedelta(days=_CANCEL_GRACE_DAYS)
        cap_day = (
            offered + timedelta(days=_CANCEL_MAX_OPEN_DAYS)
            if offered is not None
            else None
        )

        # Absence guard: did any charge at the NORMALIZED merchant key post after
        # the offer? If so, the sub is still alive → it did NOT cancel. Keep it
        # ``unverified`` UNLESS it has also blown past the open-cap, in which case
        # we stop tracking it (expire + nudge) rather than re-check forever.
        if merchant_key and offered is not None and self._charged_since(
            bridge.user_id, merchant_key, after=offered
        ):
            if cap_day is not None and as_of >= cap_day:
                self._expire_cancel_with_nudge(bridge)
                return "expired"
            return "unverified"

        # The annual-cadence guard: if the open-cap is reached BEFORE the (far-off)
        # verify horizon, expire rather than dangle a cancel offer for ~a year. For
        # short cadences the cap sits AFTER the horizon, so this never pre-empts a
        # legitimate verification.
        if cap_day is not None and as_of >= cap_day and as_of < horizon:
            self._expire_cancel_with_nudge(bridge)
            return "expired"

        if as_of >= horizon:
            # A full cadence + grace passed with no matching charge → cancelled.
            bridge.status = "verified"
            bridge.resolved_at = _now_iso()
            self.db.flush()
            return "verified"

        return "pending"

    def _charged_since(self, user_id: int, merchant_key: str, *, after: date) -> bool:
        """True if any expense at the normalized merchant key posted after *after*.

        Reuses ``categorization_service.normalize_merchant`` so the comparison is
        on the SAME normalized key the lifecycle/subscription detectors use — a
        renewal under a slightly different raw title still matches and (correctly)
        keeps the cancellation unverified."""
        from server.src.db.models import Expense as ExpenseORM
        from server.src.services.categorization_service import normalize_merchant

        rows = (
            self.db.execute(
                select(ExpenseORM.title, ExpenseORM.date).where(
                    ExpenseORM.user_id == user_id
                )
            )
            .all()
        )
        after_iso = after.isoformat()[:10]
        for title, dstr in rows:
            if not dstr or str(dstr)[:10] <= after_iso:
                continue
            if normalize_merchant(title or "") == merchant_key:
                return True
        return False

    def _expire_cancel_with_nudge(self, bridge: AssistedActionORM) -> None:
        """Expire an over-aged cancel bridge and leave one idempotent nudge."""
        bridge.status = "expired"
        bridge.resolved_at = _now_iso()
        ref = f"sub_cancel_expired:{bridge.id}"
        exists = self.db.execute(
            select(NotificationORM.id).where(
                NotificationORM.user_id == bridge.user_id,
                NotificationORM.ref == ref,
            )
        ).scalar_one_or_none()
        if exists is None:
            how = _loads(bridge.how_json)
            name = how.get("title") or how.get("merchant") or "this subscription"
            self.db.add(
                NotificationORM(
                    user_id=bridge.user_id,
                    type="subscription_cancel",
                    title="Still tracking that cancellation?",
                    message=(
                        f"I haven't been able to confirm {name} stopped charging "
                        "you yet. If you cancelled, you can dismiss this; if not, "
                        "the cancel steps are still available."
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


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except (TypeError, ValueError):
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None
