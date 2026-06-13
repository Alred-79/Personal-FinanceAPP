"""The debt boss projection (v4 §7.1).

One debt = one boss. HP = current balance in cents. Damage = real posted
payments (verified by the bank); APR accrual heals the boss (the heal IS the
interest — that's the lesson); a missed bill *empowers* the boss visually but
adds no fictional HP. Phases break at each 20% of starting HP. Victory is the
day the balance hits zero, then an informed seal-vs-banish choice.

Everything here is a PURE fold over the event log into ``boss_state``. Folds
NEVER write the ``liabilities`` table (that's liability_service's job) and never
read wall-clock time — the amounts and the as-of dates come from event payloads.

Agency law: the boss "holds ground", "regroups", "retreats" — the user never
takes narrated damage. The agency-language lint (test 14) enforces this on copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from . import folds as folds_mod
from .events import register_event_type

BOSS_STATE = "boss_state"

CRIT_MULTIPLE = 1.25  # payment > minimum × 1.25 is a crit
PHASE_FRACTION = 0.20  # a phase breaks at each 20% of starting HP

# Boss events. All forbidden for XP (the XP for a real payment rides on
# PaymentPosted, not on the boss-damage projection event).
_BOSS_EVENTS = (
    "BossDamaged",
    "BossHealed",
    "BossEmpowered",
    "BossPhaseBroken",
    "BossDefeated",
    "BossSealed",
    "BossBanished",
)
for _t in _BOSS_EVENTS:
    register_event_type(_t, 1)


# ── the juice allowlist (v4 §11) — celebrations fire ONLY for these ────────
# Payoff events only. A purchase (TxnPosted) is NEVER celebrated; near-misses
# never celebrated; streak events get the standard toast, not juice. The
# allowlist-walk test is the structural enforcement.
JUICE_EVENTS: frozenset[str] = frozenset(
    {
        "BossDamagedCrit",  # only the crit variant, not every BossDamaged
        "BossPhaseBroken",
        "BossDefeated",
        "BossSealed",
        "GoalFunded",
        "RuleExecutedSweep",  # only the sweep kind
        "LevelUp",
    }
)


def is_juice_event(event_type: str, payload: Optional[dict] = None) -> bool:
    """Whether an event should trigger a celebration. The crit/sweep variants
    are gated on the payload so plain BossDamaged / RuleExecuted never juice."""
    payload = payload or {}
    if event_type == "BossDamaged":
        return bool(payload.get("crit")) and "BossDamagedCrit" in JUICE_EVENTS
    if event_type == "RuleExecuted":
        return payload.get("kind") == "sweep" and "RuleExecutedSweep" in JUICE_EVENTS
    return event_type in JUICE_EVENTS


# ── boss_state projection access ──────────────────────────────────────────


def _boss(session: Session, liability_id) -> dict:
    return folds_mod.kv_get(session, BOSS_STATE, f"boss:{liability_id}") or {
        "liability_id": liability_id,
        "starting_hp": None,
        "hp": None,
        "phases_broken": [],  # phase indices already broken (idempotent)
        "defeated": False,
        "total_damage": 0,
        "total_heal": 0,
    }


def _boss_put(session: Session, liability_id, state: dict) -> None:
    folds_mod.kv_put(session, BOSS_STATE, f"boss:{liability_id}", state)


def _ensure_started(state: dict, starting_hp: Optional[int]) -> dict:
    if state["starting_hp"] is None and starting_hp is not None:
        state["starting_hp"] = starting_hp
        state["hp"] = starting_hp
    return state


# ── folds ──────────────────────────────────────────────────────────────────


def _phase_indices_crossed(starting_hp: int, hp_before: int, hp_after: int) -> list[int]:
    """Phase index = how many 20% bands have been cleared. Returns NEW indices
    crossed moving from hp_before to hp_after (damage lowers hp)."""
    if starting_hp <= 0:
        return []
    band = starting_hp * PHASE_FRACTION

    def cleared(hp: int) -> int:
        # number of 20% bands cleared = floor((starting - hp) / band)
        return int((starting_hp - hp) // band)

    before, after = cleared(hp_before), cleared(hp_after)
    return [i for i in range(before + 1, after + 1) if 1 <= i <= 5]


def _fold_boss_damaged(session: Session, payload: dict, meta) -> None:
    lid = payload.get("liability_id")
    if lid is None:
        return
    state = _ensure_started(_boss(session, lid), payload.get("starting_hp"))
    if state["hp"] is None:
        return
    amount = int(payload.get("amount", 0))
    hp_before = state["hp"]
    state["hp"] = max(hp_before - amount, 0)
    state["total_damage"] += amount
    # Phase breaks (idempotent per index) — recorded on state; the BossPhaseBroken
    # event is emitted by BossService (folds don't emit).
    for idx in _phase_indices_crossed(state["starting_hp"], hp_before, state["hp"]):
        if idx not in state["phases_broken"]:
            state["phases_broken"].append(idx)
    if state["hp"] <= 0:
        state["defeated"] = True
    _boss_put(session, lid, state)


def _fold_boss_healed(session: Session, payload: dict, meta) -> None:
    lid = payload.get("liability_id")
    if lid is None:
        return
    state = _ensure_started(_boss(session, lid), payload.get("starting_hp"))
    if state["hp"] is None:
        return
    amount = int(payload.get("amount", 0))
    # A defeated boss does not heal back to life from APR (defeat is permanent).
    if state["defeated"]:
        return
    state["hp"] = state["hp"] + amount
    state["total_heal"] += amount
    _boss_put(session, lid, state)


def _fold_boss_corrected(session: Session, payload: dict, meta) -> None:
    """A TxnCorrected/TxnReversed that adjusts a counted payment: HP rises by the
    compensation (truth restored). Carried as a signed ``hp_delta`` in payload."""
    lid = payload.get("liability_id")
    if lid is None:
        return
    state = _boss(session, lid)
    if state["hp"] is None:
        return
    delta = int(payload.get("hp_delta", 0))
    state["hp"] = max(state["hp"] + delta, 0)
    # Recompute defeat from the restored HP. A reversal/correction that brings HP
    # back above zero (a bounced payment, fraud, or an unlinked mis-categorized
    # payment) must UN-defeat the boss — otherwise it stays "defeated" with
    # positive HP and every future APR heal is silently dropped.
    state["defeated"] = state["hp"] <= 0
    _boss_put(session, lid, state)


def register_boss_folds() -> None:
    if any(p == BOSS_STATE for ps in folds_mod._FOLDS.values() for p, _ in ps):
        return
    folds_mod.register_fold(BOSS_STATE, "BossDamaged", _fold_boss_damaged)
    folds_mod.register_fold(BOSS_STATE, "BossHealed", _fold_boss_healed)
    # Corrections/reversals that the BossService translates into an HP delta are
    # re-published as BossHealed with a hp_delta? No — keep them explicit:
    folds_mod.register_fold(BOSS_STATE, "BossCorrected", _fold_boss_corrected)
    register_event_type("BossCorrected", 1)


def boss_view(session: Session, liability_id) -> dict:
    s = _boss(session, liability_id)
    return {
        "liability_id": liability_id,
        "hp": s["hp"],
        "starting_hp": s["starting_hp"],
        "phases_broken": sorted(s["phases_broken"]),
        "defeated": s["defeated"],
    }


# ── deterministic amortization: snowball vs avalanche ──────────────────────


@dataclass
class DebtSpec:
    principal_cents: int
    apr_bps: int
    minimum_payment_cents: int


def _total_interest(order: list[DebtSpec], extra_cents: int) -> Optional[int]:
    """Total interest (cents) to clear all debts in *order*, applying each debt's
    minimum plus a shared ``extra`` rolled onto the first unpaid debt.

    Returns ``None`` when the debts do NOT amortize — i.e. a payment can't cover
    the monthly interest, so a balance grows without bound. (A $5k card at 25%
    APR with a $50 minimum accrues ~$104/mo interest against a $50 payment: it
    never gets paid off, and compounding it for the loop bound would return a
    nonsense multi-trillion-dollar figure.) The caller surfaces "won't be paid
    off at this rate" instead of a bogus dollar delta.
    """
    balances = [d.principal_cents for d in order]
    rates = [d.apr_bps / 10_000 / 12 for d in order]
    mins = [d.minimum_payment_cents for d in order]
    total_interest = 0
    for _ in range(1200):  # up to 100 years of months — safety bound
        if all(b <= 0 for b in balances):
            return total_interest  # fully amortized
        # Accrue interest.
        for i in range(len(balances)):
            if balances[i] > 0:
                interest = round(balances[i] * rates[i])
                balances[i] += interest
                total_interest += interest
        # Pay minimums, then roll extra onto the first unpaid debt in order.
        pool = extra_cents
        for i in range(len(balances)):
            if balances[i] <= 0:
                continue
            pay = min(mins[i], balances[i])
            balances[i] -= pay
        for i in range(len(balances)):
            if pool <= 0:
                break
            if balances[i] <= 0:
                continue
            pay = min(pool, balances[i])
            balances[i] -= pay
            pool -= pay
    # Hit the loop bound with a balance still outstanding → never amortizes.
    return None


def ordering_interest_delta(
    debts: list[DebtSpec], extra_cents: int
) -> dict:
    """Compute total interest under snowball (smallest balance first) and
    avalanche (highest APR first), and the dollar delta. Deterministic — this is
    the user's OWN numbers shown on the one-time override screen.

    If EITHER ordering doesn't amortize (a thin minimum can't cover interest),
    ``amortizes`` is False and the interest/delta figures are None — the UI shows
    "won't be paid off at this rate" rather than a garbage dollar amount.
    """
    snowball = sorted(debts, key=lambda d: d.principal_cents)
    avalanche = sorted(debts, key=lambda d: -d.apr_bps)
    snow_i = _total_interest(snowball, extra_cents)
    aval_i = _total_interest(avalanche, extra_cents)
    if snow_i is None or aval_i is None:
        return {
            "amortizes": False,
            "snowball_interest_cents": None,
            "avalanche_interest_cents": None,
            "delta_cents": None,
        }
    return {
        "amortizes": True,
        "snowball_interest_cents": snow_i,
        "avalanche_interest_cents": aval_i,
        "delta_cents": snow_i - aval_i,  # positive → avalanche saves this much
    }


def monthly_apr_interest_cents(principal_cents: int, apr_bps: int) -> int:
    """Real one-month interest at the given APR (the boss 'heal'). The heal IS
    the interest — shown to the user as the actual figure on tap."""
    monthly_rate = apr_bps / 10_000 / 12
    return round(principal_cents * monthly_rate)


# ── BossService — the orchestration (emits events; folds project) ──────────


class BossService:
    """Translates real money events into boss events. Reads liabilities (via
    liability_service) and the event log; appends boss events. NEVER writes the
    liabilities table from here in a fold context — closure transitions go
    through LiabilityService."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _liab(self, liability_id, *, user_id: Optional[int] = None):
        """Load a liability. When ``user_id`` is given, the lookup is OWNERSHIP-
        SCOPED (``WHERE id == AND user_id ==``), matching liability_service's
        pattern — a foreign liability id resolves to None and the caller rejects
        it. ``user_id=None`` keeps the legacy unscoped lookup for internal
        engine callers that already hold a verified handle."""
        from ...db.models import Liability

        if user_id is None:
            return self.db.get(Liability, liability_id)
        from sqlalchemy import select

        return self.db.execute(
            select(Liability).where(
                Liability.id == liability_id, Liability.user_id == user_id
            )
        ).scalar_one_or_none()

    def register_payment(
        self, liability_id: int, amount_cents: int, *, txn_id: str,
        user_id: Optional[int] = None,
    ) -> dict:
        """A real posted payment → BossDamaged (idempotent on txn id). Crit when
        the payment exceeds minimum × 1.25. Emits BossPhaseBroken (idempotent per
        index) and BossDefeated when HP hits 0."""
        from .events import GameEventDraft, record_events

        liab = self._liab(liability_id, user_id=user_id)
        if liab is None:
            raise ValueError("liability not found")
        crit = amount_cents > liab.minimum_payment_cents * CRIT_MULTIPLE

        before = _boss(self.db, liability_id)
        phases_before = set(before.get("phases_broken", []))

        record_events(self.db, [GameEventDraft(
            stream=f"boss:{liability_id}", type="BossDamaged",
            payload={
                "liability_id": liability_id,
                "amount": amount_cents,
                "crit": crit,
                "starting_hp": liab.principal_cents,
            },
            idempotency_key=f"dmg:{liability_id}:{txn_id}",
        )])
        self.db.flush()

        after = _boss(self.db, liability_id)
        # Emit phase-break events for any NEW phase index (idempotent per index).
        for idx in sorted(set(after.get("phases_broken", [])) - phases_before):
            record_events(self.db, [GameEventDraft(
                stream=f"boss:{liability_id}", type="BossPhaseBroken",
                payload={"liability_id": liability_id, "phase": idx},
                idempotency_key=f"phase:{liability_id}:{idx}",
            )])
        # Defeat (idempotent — only fire once).
        if after.get("defeated") and not before.get("defeated"):
            record_events(self.db, [GameEventDraft(
                stream=f"boss:{liability_id}", type="BossDefeated",
                payload={"liability_id": liability_id},
                idempotency_key=f"defeat:{liability_id}",
            )])
        self.db.flush()
        return boss_view(self.db, liability_id)

    def accrue_monthly_interest(
        self, liability_id: int, period: str, *, user_id: Optional[int] = None
    ) -> int:
        """Month close → BossHealed equal to the real APR interest (idempotent
        per period). Returns the interest cents. ``user_id`` (when given) scopes
        the liability lookup to the owner."""
        from .events import GameEventDraft, record_events

        liab = self._liab(liability_id, user_id=user_id)
        if liab is None:
            raise ValueError("liability not found")
        state = _boss(self.db, liability_id)
        principal = state["hp"] if state["hp"] is not None else liab.principal_cents
        interest = monthly_apr_interest_cents(principal, liab.apr_bps)
        if interest <= 0:
            return 0
        record_events(self.db, [GameEventDraft(
            stream=f"boss:{liability_id}", type="BossHealed",
            payload={
                "liability_id": liability_id,
                "amount": interest,
                "starting_hp": liab.principal_cents,
                "period": period,
            },
            idempotency_key=f"heal:{liability_id}:{period}",
        )])
        self.db.flush()
        return interest

    def empower(self, liability_id: int, occurrence: str) -> None:
        """A missed tracked bill → BossEmpowered (visual menace only; no HP).
        Idempotent per occurrence."""
        from .events import GameEventDraft, record_events

        record_events(self.db, [GameEventDraft(
            stream=f"boss:{liability_id}", type="BossEmpowered",
            payload={"liability_id": liability_id, "occurrence": occurrence},
            idempotency_key=f"empower:{liability_id}:{occurrence}",
        )])
        self.db.flush()

    def defeat_by_date(
        self, user, liability_id: int, as_of: date, *, grace: bool = False
    ) -> dict:
        """Recompute the defeat-by-date from the current HP and payment pattern.

        Returns {date, copy_key}. Under Grace the date moves OUT and the copy key
        switches to the 'retreat' variant — never a 'you fell behind' message.
        """
        owner_id = getattr(user, "id", None)
        liab = self._liab(liability_id, user_id=owner_id)
        state = _boss(self.db, liability_id)
        hp = state["hp"] if state["hp"] is not None else (liab.principal_cents if liab else 0)
        pay = max(liab.minimum_payment_cents if liab else 0, 1)
        # Simple months-to-zero at the current minimum (interest-aware via the
        # amortization helper would be heavier; the spec wants the forecast number
        # — minimum-payment months is the deterministic default here).
        months = (hp + pay - 1) // pay if hp > 0 else 0
        result_date = _add_months(as_of, months)
        return {
            "date": result_date.isoformat(),
            "copy_key": "boss.retreat" if grace else "boss.defeat_eta",
        }


def _add_months(d: date, months: int) -> date:
    """Add *months* to *d*, preserving the day-of-month (clamped to the target
    month's length). Snapping to the 1st would put the marketed 'defeat date' up
    to ~30 days off; the user pays on roughly the same day each month, so the
    payoff lands on that day."""
    from calendar import monthrange

    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)
