"""Heat contracts — the bridge between the game and the money spine (v4 §6.2, R5).

A user composes a constraint priced in Heat against their OWN baselines; the
payoff is real — verified underspend vs. baseline can sweep into the active boss
or a goal. The honesty constraints are absolute:

  * a sweep NEVER executes for more than the VERIFIED underspend (recomputed at
    execution from posted data, not the contract's hope),
  * sweeps flow through the v1 rule engine (propose→confirm), never a direct
    money move — this app never moves money between banks,
  * essentials and LOW_CONFIDENCE baselines can't be priced,
  * a monthly Heat cap + a max-3-active-contracts guard against frugality burnout,
  * sweeps pause under Grace; abandoning costs only the forfeited bonus.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import (
    Account as AccountORM,
    CategorySettings as CategorySettingsORM,
    Expense as ExpenseORM,
    HeatContract,
)
from ...models import UserInDB
from .baselines import category_baseline

MONTHLY_HEAT_CAP = 6  # frugality-burnout guard
MAX_ACTIVE_CONTRACTS = 3

# Deterministic pricing table for cap_vs_baseline by the cap percentage.
# Tighter cap = more Heat. Only these difficulties are offered.
_CAP_PRICE = {75: 1, 50: 2, 25: 3}


class HeatError(Exception):
    """A contract cannot be priced/created — carries a plain explanation."""

    def __init__(self, reason: str, explanation: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.explanation = explanation or reason


@dataclass
class HeatPrice:
    heat: int
    category: str
    kind: str
    target_param: int


class HeatService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── pricing (deterministic, baseline-relative) ──────────────────────────

    def _is_essential(self, category: str) -> bool:
        row = self.db.execute(
            select(CategorySettingsORM).where(CategorySettingsORM.name == category)
        ).scalar_one_or_none()
        return bool(row and row.essential)

    def _is_confirmed(self, category: str) -> bool:
        row = self.db.execute(
            select(CategorySettingsORM).where(CategorySettingsORM.name == category)
        ).scalar_one_or_none()
        return bool(row and row.user_confirmed)

    def price(
        self, user: UserInDB, category: str, kind: str, target_param: int,
        as_of: Optional[date] = None,
    ) -> HeatPrice:
        """Price a candidate contract. Refuses essentials and LOW_CONFIDENCE
        baselines; only `user_confirmed` categories are valid targets."""
        as_of = as_of or date.today()
        if self._is_essential(category):
            raise HeatError("essential_category",
                            "Essentials can't carry a Heat contract.")
        if not self._is_confirmed(category):
            raise HeatError("unconfirmed_category",
                            "Confirm this category before contracting on it.")
        base = category_baseline(self.db, user.id, category, as_of)
        if base.low_confidence:
            raise HeatError("low_confidence",
                            "Not enough history to price this fairly yet.")
        if kind == "cap_vs_baseline":
            heat = _CAP_PRICE.get(target_param)
            if heat is None:
                raise HeatError("bad_cap", "Cap must be one of 75/50/25%.")
        elif kind == "extra_to_boss":
            heat = 1 + min(target_param // 50, 2)  # amount-vs-slack-ish, capped
        elif kind == "zero_dips":
            heat = 2
        else:
            raise HeatError("bad_kind", f"Unknown contract kind: {kind}")
        return HeatPrice(heat=heat, category=category, kind=kind, target_param=target_param)

    # ── creation (with vetoes) ──────────────────────────────────────────────

    def active_contracts(self, user: UserInDB, month: str) -> list[HeatContract]:
        return list(self.db.execute(
            select(HeatContract).where(
                HeatContract.user_id == user.id,
                HeatContract.month == month,
                HeatContract.status == "active",
            )
        ).scalars())

    def heat_spent(self, user: UserInDB, month: str) -> int:
        return sum(c.heat_value for c in self.active_contracts(user, month))

    def create(
        self, user: UserInDB, month: str, price: HeatPrice, *, arm: str = "cosmetic",
        as_of: Optional[date] = None,
    ) -> HeatContract:
        """Create the contract after the vetoes pass. Forecast veto: if the
        constraint would push the projection negative, refuse with explanation."""
        actives = self.active_contracts(user, month)
        if len(actives) >= MAX_ACTIVE_CONTRACTS:
            raise HeatError("too_many", "You already have three active contracts.")
        if self.heat_spent(user, month) + price.heat > MONTHLY_HEAT_CAP:
            raise HeatError("heat_cap", "That would exceed this month's Heat cap.")
        if self._forecast_would_go_negative(user, as_of or date.today()):
            raise HeatError(
                "forecast_veto",
                "Your forecast already dips low this month — easing off is wiser "
                "than a tighter constraint right now.")
        contract = HeatContract(
            user_id=user.id, category=price.category, kind=price.kind,
            target_param=price.target_param, heat_value=price.heat, month=month,
            status="active", arm=arm,
        )
        self.db.add(contract)
        self.db.flush()
        return contract

    def _forecast_would_go_negative(self, user: UserInDB, as_of: date) -> bool:
        from datetime import timedelta
        from server.src.services.forecast_service import ForecastService

        try:
            # Scheduled-only (include_burn=False): the Heat veto keys off bills
            # vs. income, not estimated discretionary burn, so its behavior is
            # stable and explainable.
            fc = ForecastService(self.db).forecast(
                user.id, as_of, as_of + timedelta(days=30), include_burn=False)
            return bool(fc.get("will_go_negative"))
        except Exception:
            return False

    # ── verification + the capped sweep ─────────────────────────────────────

    def verified_underspend_cents(
        self, user: UserInDB, contract: HeatContract, as_of: date
    ) -> int:
        """Posted-transactions-only verified underspend for *contract*. Never
        negative — a sweep can never exceed this.

        ``target_param`` is POLYMORPHIC across kinds (Step 09 fix): treating it
        as a percentage for every kind (the old single-formula bug) computed
        ``extra_to_boss``/``zero_dips`` against the wrong unit. Branch on kind:

        * ``cap_vs_baseline`` — ``target_param`` is a CAP PERCENTAGE of the
          baseline; underspend = cap − posted spend.
        * ``extra_to_boss`` — ``target_param`` is an ABSOLUTE extra-payment
          target in CENTS; the verified amount is how far the user came UNDER
          their baseline this period (the real, posted slack), clamped to the
          target. You can never sweep more slack than actually exists, and never
          more than the contracted target.
        * ``zero_dips`` — winnability is "no overdraft / no negative dip this
          period". The reward is the period's posted underspend vs baseline; a
          month that dipped is unwon (zero).
        """
        base = category_baseline(self.db, user.id, contract.category, as_of)
        acct_ids = list(self.db.execute(
            select(AccountORM.id).where(AccountORM.user_id == user.id)
        ).scalars())
        if not acct_ids:
            return 0
        from sqlalchemy import func

        first = date(int(contract.month[:4]), int(contract.month[5:7]), 1)
        spent = int(self.db.execute(
            select(func.coalesce(func.sum(ExpenseORM.amount), 0)).where(
                ExpenseORM.account_id.in_(acct_ids),
                ExpenseORM.category == contract.category,
                ExpenseORM.date >= first.isoformat(),
                ExpenseORM.date <= as_of.isoformat(),
            )
        ).scalar_one() or 0)

        kind = contract.kind
        if kind == "cap_vs_baseline":
            cap_cents = base.monthly_cents * contract.target_param // 100
            return max(cap_cents - spent, 0)

        # The verified slack vs the FULL baseline — the real money the user kept
        # under their own normal pace. Shared by extra_to_boss and zero_dips.
        slack = max(base.monthly_cents - spent, 0)

        if kind == "extra_to_boss":
            # target_param is an absolute cents target — sweep at most the
            # contracted target, and never more than the verified slack.
            target_cents = max(int(contract.target_param), 0)
            return min(slack, target_cents)

        if kind == "zero_dips":
            # Winnable iff the period had no negative dip; the reward is the
            # verified slack. An unwon (dipped) month yields zero.
            if self._had_negative_dip(user, contract.month, as_of):
                return 0
            return slack

        # Unknown kind: nothing verified (defensive — price() rejects these).
        return 0

    def _had_negative_dip(self, user: UserInDB, month: str, as_of: date) -> bool:
        """Whether any of the user's accounts is currently in overdraft (a
        negative balance) — the explicit, winnable definition for ``zero_dips``.

        Posted-data only: a clean (no-dip) month has all balances >= 0. This is
        deterministic and recomputed at execution, preserving the never-sweep-
        more-than-verified invariant."""
        balances = list(self.db.execute(
            select(AccountORM.balance).where(AccountORM.user_id == user.id)
        ).scalars())
        return any((b or 0) < 0 for b in balances)

    def sweep_amount_cents(
        self, user: UserInDB, contract: HeatContract, contracted_cents: int, as_of: date
    ) -> int:
        """The amount a sweep may move: min(verified underspend, contracted). The
        sweep can NEVER exceed the verified underspend (recomputed from posted
        data at execution time)."""
        verified = self.verified_underspend_cents(user, contract, as_of)
        return min(verified, contracted_cents)

    def abandon(self, contract: HeatContract) -> None:
        """One-tap abandon: status only, zero penalty events, bonus forfeited."""
        contract.status = "abandoned"
        self.db.flush()

    def soft_land_next_month(self, contract: HeatContract) -> HeatPrice:
        """Re-offer at 60% difficulty next month (03's soft-landing idea applied
        to Heat). For a cap contract, loosen the cap toward baseline."""
        loosened = min(100, int(contract.target_param + (100 - contract.target_param) * 0.4))
        # Snap to the nearest offered tier at-or-above the loosened cap.
        tier = min((p for p in _CAP_PRICE if p >= loosened), default=75)
        return HeatPrice(heat=_CAP_PRICE[tier], category=contract.category,
                         kind="cap_vs_baseline", target_param=tier)
