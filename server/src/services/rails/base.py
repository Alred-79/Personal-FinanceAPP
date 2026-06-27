"""Rail adapter abstraction (parent design §3.3) — Phase 2a–2b, SANDBOX ONLY.

A thin interface so an originable Bridge ``kind`` maps to a rail without
``execute()`` knowing provider details. Nothing here moves real money: the only
concrete adapter (``IncreaseAdapter``) targets the rail's *sandbox* host, and the
whole path is gated behind ``settings.rail_origination_enabled`` (default False).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class RailError(Exception):
    """Origination could not be completed at the rail (or a guard refused it).

    Raised for every pre-call guard failure AND for any rail HTTP/network error,
    so a caller never sees a half-originated state — on ``RailError`` the Bridge is
    left exactly as it was (``settlement_status`` stays None) and is still
    actionable via the manual fallback.
    """


@dataclass(frozen=True)
class FundingSource:
    """The rail's handle for the account money leaves (the paying account)."""

    rail: str
    external_id: str  # e.g. Increase account_number_id


@dataclass(frozen=True)
class FundingDest:
    """The rail's handle for the destination (own account A2A, or liability)."""

    rail: str
    external_id: str


@dataclass(frozen=True)
class OriginationResult:
    """What a rail returns once it has accepted an origination request."""

    rail: str                 # "increase" | "method"
    rail_ref: str             # provider transfer/payment id
    settlement_status: str    # "submitted" (or "settled" for instant rails)


@runtime_checkable
class RailAdapter(Protocol):
    """A money-movement provider. ``execute()`` depends only on this Protocol."""

    name: str

    def originate(
        self,
        *,
        amount_cents: int,
        source: FundingSource,
        dest: FundingDest,
        idempotency_key: str,   # MUST be stable per Bridge (parent §4.3) — verify_ref
        memo: str,
    ) -> OriginationResult:
        ...


@runtime_checkable
class FundingResolver(Protocol):
    """Resolves an internal ``Account.id`` (as the Bridge's ``source_ref`` /
    ``dest_ref`` string) to a rail funding handle.

    Until 2c onboarding exists there is no real funding source for any account, so
    the only resolver wired in 2a is a stub that RAISES ``RailError`` for every
    account — which makes ``execute()`` correctly fall back to manual.
    """

    def resolve_source(self, rail: str, account_ref: str | None) -> FundingSource:
        ...

    def resolve_dest(self, rail: str, account_ref: str | None) -> FundingDest:
        ...


class UnresolvedFundingResolver:
    """The 2a default: no account has a sandbox funding source yet, so every
    resolution raises. This is correct — origination is impossible without a
    funding source, so ``execute()`` raises pre-call and the UI offers manual."""

    def resolve_source(self, rail: str, account_ref: str | None) -> FundingSource:
        raise RailError(
            "no funding source for this account yet (onboarding lands in 2c)"
        )

    def resolve_dest(self, rail: str, account_ref: str | None) -> FundingDest:
        raise RailError(
            "no funding destination for this account yet (onboarding lands in 2c)"
        )


# Rail selection — a pure mapping, no branching in ``execute()`` (parent §3.3).
# ``debt_payment`` (Method) is deferred to 2d; ``bill_payment`` / ``tax_payment``
# stay manual in Phase 2 (parent §6.3).
_RAIL_FOR_KIND = {
    "transfer": "increase",      # A2A between the user's own accounts
    "goal_funding": "increase",  # sweep into a savings/goal account
}
ORIGINABLE_KINDS = frozenset(_RAIL_FOR_KIND)


def rail_for_kind(kind: str) -> str:
    """The rail name for an originable kind, or raise ``RailError`` if not one."""
    try:
        return _RAIL_FOR_KIND[kind]
    except KeyError:
        raise RailError(f"kind {kind!r} is not originable (stays manual)")
