"""Purpose-specific account totals with explicit inclusion and provenance.

The same raw balance does not answer every financial question. Near-term cash
uses liquid depository funds; net worth includes assets and subtracts amounts
owed. This module is the one interpretation seam shared by REST, forecast,
Safe-to-Spend, and net-worth services.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import Account as AccountORM


Purpose = Literal["near_term_cash", "forecast", "net_worth"]

_LIQUID_TYPES = {
    "checking",
    "savings",
    "spending",
    "cash",
    "depository",
    "cash management",
    "money market",
}
_NONLIQUID_TYPES = {"investment", "brokerage", "retirement", "property", "asset"}
_LIABILITY_TYPES = {"credit", "credit card", "loan", "mortgage", "liability"}


def infer_semantic_role(account_type: str | None, subtype: str | None = None) -> str:
    """Infer only well-known account roles; unfamiliar types stay reviewable."""
    values = {str(account_type or "").strip().lower(), str(subtype or "").strip().lower()}
    if values & _LIABILITY_TYPES:
        return "liability"
    if values & _LIQUID_TYPES:
        return "liquid_asset"
    if values & _NONLIQUID_TYPES:
        return "nonliquid_asset"
    return "unknown"


@dataclass(frozen=True)
class AccountSummary:
    purpose: Purpose
    total_cents: int
    state: str
    components: list[dict]
    exclusions: list[dict]

    def to_dict(self) -> dict:
        return {
            "purpose": self.purpose,
            "total_cents": self.total_cents,
            "state": self.state,
            "components": self.components,
            "exclusions": self.exclusions,
        }


class AccountSemanticsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _current_cents(account: AccountORM) -> int:
        # Manual balances are transaction-maintained through the legacy field.
        # Linked balances are bank-authoritative and use the raw current value.
        if account.plaid_account_id is None:
            return int(account.balance or 0)
        if account.current_balance is not None:
            return int(account.current_balance)
        return int(account.balance or 0)

    @staticmethod
    def _currency(account: AccountORM) -> tuple[str | None, str]:
        if account.unofficial_currency_code:
            return account.unofficial_currency_code, "unofficial_currency"
        if account.iso_currency_code:
            return account.iso_currency_code.upper(), "reported_currency"
        if account.plaid_account_id is None:
            return "USD", "manual_usd"
        # Legacy linked rows predate raw currency storage. Preserve their
        # usefulness during migration, but mark the answer as limited so the
        # UI never presents the assumption as bank-reported fact.
        return "USD", "legacy_currency_assumed"

    @staticmethod
    def _observed_at(account: AccountORM) -> datetime | None:
        return account.balance_observed_at or account.plaid_balance_refreshed_at or account.last_updated

    def summarize(self, user_id: int, purpose: Purpose) -> AccountSummary:
        accounts = self.db.execute(
            select(AccountORM)
            .where(AccountORM.user_id == user_id)
            .order_by(AccountORM.id)
        ).scalars().all()
        if not accounts:
            return AccountSummary(purpose, 0, "empty", [], [])

        total = 0
        limited = False
        components: list[dict] = []
        exclusions: list[dict] = []
        now = datetime.now(timezone.utc)

        for account in accounts:
            role = account.semantic_role or infer_semantic_role(account.type, account.subtype)
            currency, currency_quality = self._currency(account)
            observed_at = self._observed_at(account)
            base = {
                "account_id": int(account.id),
                "name": account.name,
                "role": role,
                "currency": currency,
                "observed_at": observed_at.isoformat() if observed_at else None,
            }

            if currency != "USD":
                limited = True
                exclusions.append({**base, "reason": currency_quality})
                continue
            if currency_quality == "legacy_currency_assumed":
                limited = True
            if role == "unknown":
                limited = True
                exclusions.append({**base, "reason": "account_role_unknown"})
                continue

            current = self._current_cents(account)
            quality = "manual" if account.plaid_account_id is None else "fresh_current"
            value = current

            if purpose in {"near_term_cash", "forecast"}:
                if role != "liquid_asset":
                    exclusions.append({**base, "reason": "not_liquid_cash"})
                    continue
                if account.plaid_account_id is not None and account.available_balance is not None:
                    value = int(account.available_balance)
                    quality = "reported_available"
                elif account.plaid_account_id is not None:
                    limited = True
                    quality = "current_fallback"
            elif role == "liability":
                # Plaid liability balances are positive when money is owed. A
                # negative card balance is an overpayment/credit and therefore
                # increases, rather than reduces, net worth. Legacy/manual
                # liabilities historically used signed negative balances, so
                # preserve that convention while also treating a manually
                # entered positive amount as an amount owed.
                if account.plaid_account_id is not None:
                    value = -current
                    quality = "amount_owed" if current >= 0 else "credit_balance"
                else:
                    value = -abs(current)
                    quality = "manual_amount_owed"

            # A bank-linked balance with no provenance is still usable as a
            # limited fact, never as an unqualified safe-money answer.
            if account.plaid_account_id is not None and observed_at is None:
                limited = True
                quality = "freshness_missing"
            elif account.plaid_account_id is not None and observed_at is not None:
                stamp = observed_at
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                age_hours = max(0.0, (now - stamp).total_seconds() / 3600)
                if age_hours > 36:
                    limited = True
                    quality = "stale_balance"

            total += value
            components.append({**base, "signed_cents": value, "quality": quality})

        state = "limited" if limited else "ready"
        if not components:
            state = "limited" if exclusions else "empty"
        return AccountSummary(purpose, total, state, components, exclusions)

    def total_cents(self, user_id: int, purpose: Purpose) -> int:
        return self.summarize(user_id, purpose).total_cents
