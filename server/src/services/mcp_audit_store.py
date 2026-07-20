"""Persistence for the MCP audit trail (the Agent Vault's read-back store).

Lives OUTSIDE ``mcp/`` on purpose. The MCP import guard
(``test_mcp_import_guard.py``) forbids every module under ``mcp/`` except
``vault.py`` from importing a DB session — that's what keeps the agent's read
boundary enforceable rather than aspirational. So ``mcp/audit.py`` delegates its
row-write here instead of touching the DB itself. This is not part of the agent's
read capability; it's the owner's audit record, written on its own committing
session (the vault's read session always rolls back, so an audit row must not
ride it).
"""

from __future__ import annotations

import logging
from typing import Optional


_log = logging.getLogger(__name__)


def persist(
    *,
    user_id: Optional[int],
    key_id: Optional[int],
    resource: str,
    decision: str,
    latency_ms: float = 0.0,
    params_hash: str = "",
) -> None:
    """Best-effort: write ONE audit row on a fresh, short-lived committing session.

    Skips rows with no ``user_id`` (an unknown-key flood has nobody to attribute
    it to, and persisting it would be a DoS amplifier). Never raises — auditing
    must not break a read; the structured log line already happened upstream.
    """
    if user_id is None:
        return
    try:
        from server.src.db.session import SessionLocal
        from server.src.db.models import MCPAuditLog
        from server.src.db.rls import set_tenant

        db = SessionLocal()
        try:
            # Load-bearing under RLS: this session is opened privately here, so it
            # sits outside every request-scoped tenant binding — and nothing on the
            # MCP path sets ``user_id_var``, so the ``after_begin`` net in
            # db/session.py cannot bind it either. Without this the policy's
            # WITH CHECK tests ``user_id`` against an unset GUC (NULL), rejects the
            # INSERT, and the blanket except below swallows it: the audit trail
            # silently empties in exactly the deployments that enabled RLS.
            # No-ops on SQLite. Must precede the INSERT to share its transaction.
            set_tenant(db, user_id)
            db.add(
                MCPAuditLog(
                    user_id=user_id,
                    key_id=key_id,
                    resource=resource,
                    decision=decision,
                    latency_ms=round(latency_ms, 2),
                    params_hash=params_hash,
                )
            )
            db.commit()
        finally:
            db.close()
    except Exception:
        # Still never re-raised: auditing must not break a read. But it IS
        # reported — a silently discarded audit row is how the RLS tenant-binding
        # bug stayed invisible, and an audit trail that can empty itself without
        # a signal is worse than one that fails loudly.
        _log.warning(
            "mcp audit row discarded (user_id=%s resource=%s decision=%s)",
            user_id,
            resource,
            decision,
            exc_info=True,
        )
