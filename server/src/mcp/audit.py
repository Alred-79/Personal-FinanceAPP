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


def record_failure(
    *,
    reason: str,
    key_id: Optional[int] = None,
    user_id: Optional[int] = None,
    client: Optional[str] = None,
) -> None:
    """Emit a structured audit line for a *rejected* MCP request.

    Unlike :func:`record` (which audits resolved tool calls), this audits the
    deny / throttle paths in the auth middleware where we usually do **not**
    yet have a principal (the key was unknown, the owner disabled, or the
    request was throttled before resolution). ``user_id``/``key_id`` are
    therefore optional.

    Parameters
    ----------
    reason : str
        Machine-readable cause — one of ``"unknown_key"`` | ``"disabled"`` |
        ``"rate_limited"`` | ``"ip_rate_limited"``. This is the *real* reason
        for the owner's audit trail, even though the caller's deny message
        stays opaque.
    key_id, user_id : int or None
        Populated only when a principal was resolved before the failure
        (e.g. the per-key throttle trips after resolution).
    client : str or None
        The (proxy-aware) client key, for IP-throttle failures. Never a raw
        credential.

    The audit store is currently log-only (MEDIUM finding); persisting these
    rows to a DB-backed store is backlogged.
    """
    entry = {
        "user_id": user_id,
        "key_id": key_id,
        "resource": "auth",
        "decision": "deny",
        "reason": reason,
    }
    if client is not None:
        entry["client"] = client
    _audit_log.warning(json.dumps(entry, separators=(",", ":")))
