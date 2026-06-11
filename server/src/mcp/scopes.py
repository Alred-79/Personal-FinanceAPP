"""MCP scope canonicalization.

Two scope formats exist in the wild: the legacy ``<resource>:read`` form kept for
existing keys/tests, and the modern ``read:<resource>`` form that every tool and
the policy gate actually check. A key minted with legacy scopes authenticates but
then fails every tool call, so we normalize legacy → modern at both ends:
``MCPKeyService.create`` (so new keys store the modern form) and
``MCPKeyService.resolve`` (so already-issued legacy keys start working without
reissue).

Legacy write/chat scopes have no read tool behind them and map to nothing usable;
they are simply dropped during normalization.
"""

from __future__ import annotations

# Legacy scope string → modern equivalent. Scopes that grant no MCP read tool
# (writes, assistant:chat) are intentionally absent and get dropped.
LEGACY_SCOPE_MAP: dict[str, str] = {
    "transactions:read": "read:transactions",
    "budgets:read": "read:budgets",
    "accounts:read": "read:accounts",
}


def normalize_scope(scope: str) -> str | None:
    """Return the modern form of *scope*, or ``None`` if it grants nothing usable.

    Modern scopes pass through unchanged. Legacy read scopes are mapped. Legacy
    write/chat scopes (no read tool behind them) return ``None``.
    """
    if scope in LEGACY_SCOPE_MAP:
        return LEGACY_SCOPE_MAP[scope]
    if scope.startswith("read:"):
        return scope
    # Unknown legacy form (e.g. transactions:write, assistant:chat) → nothing usable.
    if ":" in scope and not scope.startswith("read:"):
        return None
    return scope


def normalize_scopes(scopes: list[str]) -> list[str]:
    """Normalize a list of scopes to the modern form, dropping unusable ones.

    Order-preserving and de-duplicated.
    """
    out: list[str] = []
    seen: set[str] = set()
    for s in scopes:
        modern = normalize_scope(s)
        if modern is not None and modern not in seen:
            seen.add(modern)
            out.append(modern)
    return out
