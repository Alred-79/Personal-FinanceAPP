"""MCP structured audit logger.

Emits one structured JSON line per request through the ``mcp.audit`` logger.
**Never** logs raw keys or raw parameter values — only a truncated SHA-256
hash of the canonical JSON-encoded params.

Usage::

    from server.src.mcp.audit import record

    record(
        user_id=principal.user_id,
        key_id=principal.key_id,
        resource="transactions:read",
        params={"start": "2026-01-01", "end": "2026-01-31"},
        decision="allow",
        latency_ms=12.3,
    )
"""

import hashlib
import json
import logging
from typing import Any, Optional


_audit_log = logging.getLogger("mcp.audit")


def _canonical_params_hash(params: Optional[dict[str, Any]]) -> str:
    """Return a short, deterministic, order-independent hash of *params*.

    The canonical form is ``json.dumps(params, sort_keys=True)`` so that
    ``{"a":1,"b":2}`` and ``{"b":2,"a":1}`` produce the same hash.

    Returns the first 16 hex chars of the SHA-256 digest.  Returns an empty
    string when *params* is ``None`` or empty.
    """
    if not params:
        return ""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def record(
    *,
    user_id: int,
    key_id: int,
    resource: str,
    params: Optional[dict[str, Any]] = None,
    decision: str,
    latency_ms: float = 0.0,
) -> None:
    """Emit a single structured audit line.

    Parameters
    ----------
    user_id : int
        The authenticated user performing the request.
    key_id : int
        The MCP key id used for the request.
    resource : str
        The resource or tool being accessed (e.g. ``"transactions:read"``).
    params : dict or None
        The request parameters (hashed, never logged raw).
    decision : str
        ``"allow"`` or ``"deny"`` (or a short reason string).
    latency_ms : float
        How long the request took, in milliseconds.
    """
    entry = {
        "user_id": user_id,
        "key_id": key_id,
        "resource": resource,
        "params_hash": _canonical_params_hash(params),
        "decision": decision,
        "latency_ms": round(latency_ms, 2),
    }
    _audit_log.info(json.dumps(entry, separators=(",", ":")))
