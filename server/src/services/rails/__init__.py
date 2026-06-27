"""Rail adapters (Phase 2a–2b, SANDBOX ONLY).

A ``RailAdapter`` is the thin seam between an originable Bridge kind and a concrete
money-movement provider, so ``AssistedActionService.execute()`` never knows
provider details. See docs/PHASE2A-SANDBOX-IMPLEMENTATION.md and the parent
design §3.3. Everything here points only at a rail's *sandbox* host — no real
funds, and the whole path is dark behind ``settings.rail_origination_enabled``.
"""

from server.src.services.rails.base import (
    FundingDest,
    FundingResolver,
    FundingSource,
    ORIGINABLE_KINDS,
    OriginationResult,
    RailAdapter,
    RailError,
    rail_for_kind,
)
from server.src.services.rails.increase import IncreaseAdapter

__all__ = [
    "FundingDest",
    "FundingResolver",
    "FundingSource",
    "ORIGINABLE_KINDS",
    "OriginationResult",
    "RailAdapter",
    "RailError",
    "rail_for_kind",
    "IncreaseAdapter",
]
