"""Challenges — tiered, exit-mandatory, never staked (v4 §8.6).

Tier semantics (Law 2 made structural):

* **T1 (full XP)** — a predicate over POSTED transactions only, judged by code.
  The predicate reads ``TxnPosted`` EVENTS, so pending transactions can never
  be judged (pending emits no event — package 08 fog). The LLM may write
  flavor verdict text AFTER the engine's boolean; the text feeds nothing.
* **T2 (reduced XP)** — needs an external reference fact. Tavily supplies the
  references and the LLM produces a STRUCTURED verdict
  (:mod:`challenge_verdict`); THIS module — the engine — awards XP only from
  the structured field, and only when ``evidence_ref`` re-resolves to a
  fetched source. Un-resolvable evidence → no award, the challenge quietly
  voids (pro-player: the user never loses anything to a flaky verdict).
* **T3 (cosmetic)** — self-report, one tap. No XP, cosmetic credit only, and
  NO verification call is made (no verification theater — cheating is priced
  in by making the reward cosmetic).

Exits (mandatory on every challenge): success → a graduation offer (03's
rail: make it a standing Rule); failure/abandon → ``soft_land`` (status only,
no penalty events, a smaller re-offer). Challenges never stake anything, so
the StepBet anti-pattern (losers ending below baseline) cannot be expressed.

Sourcing: habit-monster targets and Heat-adjacent categories, under the same
caps as Heat — no essentials, no low-confidence baselines, ≤2 active.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import (
    CategorySettings as CategorySettingsORM,
    Challenge,
    GameEvent,
    Rule as RuleORM,
)
from ...models import UserInDB
from .events import GameEventDraft, record_events, register_event_type
from .graduation import DECLINE_COOLDOWN_DAYS

for _t in ("ChallengeMet", "ChallengeSoftLanded"):
    register_event_type(_t, 1)

MAX_ACTIVE_CHALLENGES = 2  # same pest-avoidance cap as Heat / habit-monsters

# XP by tier, read by xp.xp_for_event for ChallengeMet payloads. T3 is ZERO by
# construction — self-reports are cosmetic-only, so lying earns nothing real.
TIER_XP = {1: 25, 2: 10, 3: 0}


class ChallengeError(Exception):
    def __init__(self, reason: str, explanation: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.explanation = explanation or reason


@dataclass(frozen=True)
class ChallengeKind:
    key: str
    tier: int
    label_term: str  # term-catalog key; copy never hardcoded here
    default_days: int


# The registry of offerable kinds. Instances live in the ``challenges`` table.
CHALLENGE_KINDS: dict[str, ChallengeKind] = {
    "t1_category_free_week": ChallengeKind(
        key="t1_category_free_week", tier=1,
        label_term="challenge.t1_category_free_week", default_days=7,
    ),
    "t2_reference_check": ChallengeKind(
        key="t2_reference_check", tier=2,
        label_term="challenge.t2_reference_check", default_days=7,
    ),
    "t3_self_report": ChallengeKind(
        key="t3_self_report", tier=3,
        label_term="challenge.t3_self_report", default_days=3,
    ),
}


class ChallengeService:
    """Owns ``challenges`` instances. The engine: every award decision is made
    here from engine-readable data; LLM output never feeds it (Law 2)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── sourcing + offer (the same caps as Heat) ────────────────────────────

    def _category_settings(self, category: str) -> Optional[CategorySettingsORM]:
        return self.db.execute(
            select(CategorySettingsORM).where(CategorySettingsORM.name == category)
        ).scalar_one_or_none()

    def active(self, user: UserInDB) -> list[Challenge]:
        return list(self.db.execute(
            select(Challenge).where(
                Challenge.user_id == user.id, Challenge.status == "active"
            )
        ).scalars())

    def offer(
        self, user: UserInDB, key: str, category: str, starts_on: date,
        *, params: Optional[dict] = None, days: Optional[int] = None,
    ) -> Challenge:
        """Create an active challenge instance after the caps pass."""
        kind = CHALLENGE_KINDS.get(key)
        if kind is None:
            raise ChallengeError("unknown_kind", f"Unknown challenge kind: {key}")
        if len(self.active(user)) >= MAX_ACTIVE_CHALLENGES:
            raise ChallengeError("too_many", "Two challenges are already running.")
        if kind.tier in (1, 2) and category:
            settings_row = self._category_settings(category)
            if settings_row is not None and settings_row.essential:
                raise ChallengeError(
                    "essential_category", "Essentials never carry a challenge.")
            from .baselines import category_baseline

            base = category_baseline(self.db, user.id, category, starts_on)
            if base.low_confidence:
                raise ChallengeError(
                    "low_confidence", "Not enough history to judge this fairly.")
        suppressed = self._suppressed_until(user, key)
        if suppressed is not None and starts_on.isoformat() < suppressed:
            raise ChallengeError(
                "suppressed", "This offer is resting for now.")
        ends_on = starts_on + timedelta(days=(days or kind.default_days))
        challenge = Challenge(
            user_id=user.id, key=key, tier=kind.tier, category=category,
            status="active", starts_on=starts_on.isoformat(),
            ends_on=ends_on.isoformat(), params_json=json.dumps(params or {}),
        )
        self.db.add(challenge)
        self.db.flush()
        return challenge

    def _suppressed_until(self, user: UserInDB, key: str) -> Optional[str]:
        rows = self.db.execute(
            select(Challenge.suppressed_until).where(
                Challenge.user_id == user.id,
                Challenge.key == key,
                Challenge.suppressed_until.isnot(None),
            )
        ).scalars().all()
        return max(rows) if rows else None

    def source_candidates(self, user: UserInDB, as_of: date) -> list[dict]:
        """Offerable T1 candidates from habit-monster targets, under the caps.
        Faded (graduated) metrics never source a challenge."""
        from .fade import is_faded
        from .habit_monsters import detect_monsters

        out = []
        for monster in detect_monsters(self.db, user, as_of):
            category = monster["key"]
            if is_faded(self.db, user, category):
                continue
            settings_row = self._category_settings(category)
            if settings_row is not None and settings_row.essential:
                continue
            out.append({
                "key": "t1_category_free_week", "category": category,
                "tier": 1, "reason": monster["reason"],
            })
        return out[:MAX_ACTIVE_CHALLENGES]

    # ── T1: judged by code over posted events only ──────────────────────────

    def _posted_txn_count(
        self, categories: list[str], starts_on: str, ends_on: str
    ) -> int:
        """Posted transactions in the window matching *categories*. Reads
        ``TxnPosted`` EVENTS — pending transactions emit no event, so a pending
        charge is structurally invisible to the judge (pending never judges)."""
        rows = self.db.execute(
            select(GameEvent.payload).where(GameEvent.type == "TxnPosted")
        ).scalars().all()
        wanted = {c.lower() for c in categories}
        count = 0
        for raw in rows:
            payload = json.loads(raw)
            if payload.get("kind") != "expense":
                continue
            if (payload.get("category") or "").lower() not in wanted:
                continue
            if starts_on <= (payload.get("date") or "") <= ends_on:
                count += 1
        return count

    def _gap_days_in_window(self, starts_on: str, ends_on: str) -> int:
        """Days of the window covered by a sync gap (from the event log)."""
        events = self.db.execute(
            select(GameEvent).where(
                GameEvent.type.in_(("SyncGapOpened", "SyncGapClosed"))
            ).order_by(GameEvent.id)
        ).scalars().all()
        w_start = date.fromisoformat(starts_on)
        w_end = date.fromisoformat(ends_on)
        covered: set[str] = set()
        open_since: Optional[date] = None
        for ev in events:
            payload = json.loads(ev.payload)
            day_raw = payload.get("opened_at") or payload.get("closed_at") or payload.get("date")
            try:
                day = date.fromisoformat(str(day_raw)[:10])
            except (TypeError, ValueError):
                continue
            if ev.type == "SyncGapOpened" and open_since is None:
                open_since = day
            elif ev.type == "SyncGapClosed" and open_since is not None:
                cursor = max(open_since, w_start)
                while cursor <= min(day, w_end):
                    covered.add(cursor.isoformat())
                    cursor += timedelta(days=1)
                open_since = None
        if open_since is not None:  # still open through the window's end
            cursor = max(open_since, w_start)
            while cursor <= w_end:
                covered.add(cursor.isoformat())
                cursor += timedelta(days=1)
        return len(covered)

    def judge_t1(self, user: UserInDB, challenge: Challenge) -> str:
        """Judge a T1 challenge at its window end. Returns the final status.

        GRAY logic (pro-player): a sync gap inside the window makes the week
        unverifiable → the challenge VOIDS quietly. No award, no penalty, no
        suppression — it can simply be re-offered later.
        """
        if challenge.status != "active":
            return challenge.status
        if self._gap_days_in_window(challenge.starts_on, challenge.ends_on) >= 1:
            challenge.status = "void"  # quiet: no event, no award, no penalty
            self.db.flush()
            return challenge.status
        params = json.loads(challenge.params_json or "{}")
        categories = params.get("categories") or [challenge.category]
        offending = self._posted_txn_count(
            categories, challenge.starts_on, challenge.ends_on
        )
        if offending == 0:
            return self._resolve_met(user, challenge)
        return self.soft_land_challenge(user, challenge)

    # ── T2: the engine awards from the structured field ONLY ───────────────

    def resolve_t2(
        self, user: UserInDB, challenge: Challenge, verdict: dict,
        fetched_references: list[dict],
    ) -> str:
        """Resolve a T2 challenge from the STRUCTURED verdict.

        THE award call site (Law 2): XP flows only from ``verdict["met"]`` —
        never from verdict text — and only when ``evidence_ref`` re-resolves to
        a source THIS engine fetched. Un-resolvable evidence → quiet void.
        """
        if challenge.status != "active":
            return challenge.status
        challenge.verdict_json = json.dumps(verdict, sort_keys=True)
        fetched_urls = {r.get("url") for r in fetched_references if r.get("url")}
        evidence = verdict.get("evidence_ref") or ""
        if bool(verdict.get("met")) and evidence in fetched_urls:
            return self._resolve_met(user, challenge)
        if not bool(verdict.get("met")):
            return self.soft_land_challenge(user, challenge)
        # met=true but the evidence doesn't resolve → quiet void (pro-player).
        challenge.status = "void"
        self.db.flush()
        return challenge.status

    # ── T3: cosmetic self-report (no verification theater) ─────────────────

    def complete_t3(self, user: UserInDB, challenge: Challenge) -> str:
        """One-tap self-report. Cosmetic credit only, zero XP (TIER_XP[3] = 0),
        and deliberately NO verification call of any kind — we don't pretend to
        check what we can't check."""
        if challenge.status != "active":
            return challenge.status
        challenge.cosmetic_credit = 1
        challenge.status = "met"
        self.db.flush()
        record_events(self.db, [GameEventDraft(
            stream="player", type="ChallengeMet",
            payload={"key": challenge.key, "tier": 3, "self_report": True},
            idempotency_key=f"challenge_met:{user.id}:{challenge.id}",
        )])
        self.db.flush()
        return challenge.status

    # ── exits: graduation (success) and the soft landing (everything else) ──

    def _resolve_met(self, user: UserInDB, challenge: Challenge) -> str:
        challenge.status = "met"
        self.db.flush()
        record_events(self.db, [GameEventDraft(
            stream="player", type="ChallengeMet",
            payload={"key": challenge.key, "tier": challenge.tier,
                     "category": challenge.category},
            idempotency_key=f"challenge_met:{user.id}:{challenge.id}",
        )])
        self.db.flush()
        return challenge.status

    def graduation_offer(self, challenge: Challenge) -> dict:
        """The standing-rule proposal a met challenge earns (03's rail). An
        OFFER object only — accepting is a separate, user-confirmed step."""
        return {
            "kind": "standing_rule",
            "challenge_id": challenge.id,
            "category": challenge.category,
            "rationale_term": "challenge.graduation.rationale",
        }

    def accept_graduation(self, user: UserInDB, challenge: Challenge) -> RuleORM:
        """The user ACCEPTS the graduation offer → a standing Rule exists.

        This is the confirm half of propose→confirm — a user-initiated action
        (the same write the rules router performs), not autonomous game code.
        """
        rule = RuleORM(
            user_id=user.id,
            name=f"Standing: {challenge.category or challenge.key}",
            enabled=1,
            conditions=json.dumps(
                [{"field": "category", "op": "eq", "value": challenge.category}]
            ),
            action_type="notify",
            action_params=json.dumps({"origin": "challenge_graduation"}),
        )
        self.db.add(rule)
        self.db.flush()
        return rule

    def decline_graduation(self, user: UserInDB, challenge: Challenge, today: date) -> None:
        """Declining suppresses re-offers of this challenge kind for 30 days."""
        challenge.suppressed_until = (
            today + timedelta(days=DECLINE_COOLDOWN_DAYS)
        ).isoformat()
        self.db.flush()

    def soft_land_challenge(self, user: UserInDB, challenge: Challenge) -> str:
        """Failure/abandon → the soft landing. Status + ONE status-marker event;
        no penalty event exists, nothing is deducted, user state stays at
        baseline in every respect. Re-offer arrives smaller (graduation.soft_land
        provides the copy/re-offer shape)."""
        challenge.status = "soft_landed"
        self.db.flush()
        record_events(self.db, [GameEventDraft(
            stream="player", type="ChallengeSoftLanded",
            payload={"key": challenge.key, "tier": challenge.tier},
            idempotency_key=f"challenge_soft:{user.id}:{challenge.id}",
        )])
        self.db.flush()
        return challenge.status

    # ── the read surface ────────────────────────────────────────────────────

    def view(self, user: UserInDB) -> list[dict]:
        rows = self.db.execute(
            select(Challenge).where(Challenge.user_id == user.id)
            .order_by(Challenge.id.desc())
        ).scalars().all()
        return [
            {
                "id": c.id, "key": c.key, "tier": c.tier, "category": c.category,
                "status": c.status, "starts_on": c.starts_on, "ends_on": c.ends_on,
                "cosmetic_credit": bool(c.cosmetic_credit),
            }
            for c in rows
        ]
