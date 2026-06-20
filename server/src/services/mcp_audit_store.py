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

from typing import Optional


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

        db = SessionLocal()
        try:
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
    except Exception:  # pragma: no cover - audit must never break a read
        pass
