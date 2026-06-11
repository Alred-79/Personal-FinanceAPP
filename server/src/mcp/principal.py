"""Principal — the resolved identity object for MCP requests.

After a raw API key is hashed and looked up, `MCPKeyService.resolve` returns a
`Principal`.  Every downstream authorization check uses this frozen dataclass as
the single source of identity.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    """Immutable identity resolved from a valid MCP API key.

    Attributes:
        user_id:  The database ``users.id`` that owns the key.
        key_id:   The database ``mcp_keys.id`` of the key that was resolved.
        scopes:   The set of permission scopes granted by the key.
    """

    user_id: int
    key_id: int
    scopes: frozenset[str]
