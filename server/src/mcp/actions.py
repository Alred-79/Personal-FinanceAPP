"""MCP propose door — the only *write* path from the MCP side.

This is the Tier-2 counterpart to ``vault.py``. Where the vault is read-only
(opens a session, never commits, always rolls back), this door creates exactly
one thing — an Assisted-Action *Bridge* in ``status="proposed"`` — and COMMITS
it. It is deliberately the narrowest possible write:

* It NEVER moves money and NEVER executes. A Bridge is a *suggestion*: the app
  computes the exact real-world action and the human still taps "execute" in-app
  (which runs the separate, human-gated origination flow). So an agent holding
  ``propose:actions`` can draft a proposal, not perform a transfer.
* The user id comes from the verified capability token, never a tool argument —
  identical to the vault, so an agent can't propose on someone else's behalf.
* It ships dark behind ``settings.mcp_propose_enabled`` (default False), exactly
  as the read surface ships dark behind ``mcp_enabled``.

Like ``vault.py``, this module is a sanctioned DB door: it is the ONE other
``mcp/`` module permitted to import a database session (the import guard in the
test suite enforces that the set of doors is exactly {vault.py, actions.py}).
"""

import json
import time

from server.src.db.rls import set_tenant
from server.src.db.session import SessionLocal
from server.src.money import cents_to_dollars, dollars_to_cents
from server.src.settings import settings
from server.src.mcp.audit import record as audit_record
from server.src.mcp.policy import verify_capability
from server.src.services.assisted_action_service import (
    AssistedActionError,
    AssistedActionService,
)

_REQUIRED_SCOPE = "propose:actions"


class ProposeError(Exception):
    """Raised for a denied or malformed propose request.

    Callers map this to a clean MCP error — never a raw traceback, never a 500.
    """


def _to_dict(bridge) -> dict:
    """Shape a created Bridge for the MCP response (money in dollars)."""
    try:
        how = json.loads(bridge.how_json or "{}")
    except (TypeError, ValueError):
        how = {}
    return {
        "id": bridge.id,
        "kind": bridge.kind,
        "amount": cents_to_dollars(bridge.amount_cents),
        "source_ref": bridge.source_ref,
        "dest_ref": bridge.dest_ref,
        "rationale": bridge.rationale,
        "how": how,
        "status": bridge.status,
        "settlement_status": bridge.settlement_status,
        "verify_ref": bridge.verify_ref,
        "created_at": bridge.created_at,
    }


def propose(
    capability_token: str,
    *,
    kind: str,
    amount: float,
    rationale: str,
    source_ref: str | None = None,
    dest_ref: str | None = None,
    how: dict | None = None,
    **_ignored,
) -> dict:
    """Draft an Assisted-Action Bridge and commit it.

    ``amount`` is in DOLLARS (converted to integer cents here). ``**_ignored``
    deliberately swallows any extra keyword (e.g. a ``user_id`` an agent might
    try to pass) — the user is always taken from the capability token, so such
    an argument can never take effect.

    Steps: verify capability → require ``propose:actions`` → validate input →
    write + commit → audit. Raises ``ProposeError`` (clean) on any denial or bad
    input; nothing is written when it raises.
    """
    t0 = time.monotonic()

    # Step 0 — ship dark. The whole door is off unless explicitly enabled.
    if not settings.mcp_propose_enabled:
        audit_record(
            user_id=0, key_id=0, resource=f"propose:{kind}",
            decision="deny:propose_disabled",
            latency_ms=(time.monotonic() - t0) * 1000,
        )
        raise ProposeError("The MCP propose door is disabled on this deployment.")

    # Step 1 — verify the capability token (same family/audience as the vault).
    try:
        claims = verify_capability(capability_token)
    except Exception as exc:
        audit_record(
            user_id=0, key_id=0, resource=f"propose:{kind}",
            decision="deny:invalid_token",
            latency_ms=(time.monotonic() - t0) * 1000,
        )
        raise ProposeError(f"Invalid capability token: {exc}") from exc

    uid = int(claims["uid"])
    key_id = int(claims.get("kid", 0))
    scopes = set(claims.get("scopes", []))

    # Step 2 — the capability must actually carry the propose scope.
    if _REQUIRED_SCOPE not in scopes:
        audit_record(
            user_id=uid, key_id=key_id, resource=f"propose:{kind}",
            decision="deny:missing_scope",
            latency_ms=(time.monotonic() - t0) * 1000,
        )
        raise ProposeError(
            f"Capability is missing the required '{_REQUIRED_SCOPE}' scope."
        )

    # Step 3 — validate amount before touching the DB.
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        audit_record(
            user_id=uid, key_id=key_id, resource=f"propose:{kind}",
            decision="deny:bad_amount",
            latency_ms=(time.monotonic() - t0) * 1000,
        )
        raise ProposeError("'amount' must be a number of dollars.")
    if amount <= 0:
        audit_record(
            user_id=uid, key_id=key_id, resource=f"propose:{kind}",
            decision="deny:bad_amount",
            latency_ms=(time.monotonic() - t0) * 1000,
        )
        raise ProposeError("'amount' must be positive.")
    amount_cents = dollars_to_cents(amount)

    # Step 4 — write + commit, scoped to the token's user.
    db = SessionLocal()
    if settings.enable_rls:
        set_tenant(db, uid)
    try:
        bridge = AssistedActionService(db).propose(
            uid,
            kind=kind,
            amount_cents=amount_cents,
            rationale=rationale or "",
            source_ref=source_ref,
            dest_ref=dest_ref,
            how=how,
        )
        result = _to_dict(bridge)
        db.commit()
        audit_record(
            user_id=uid, key_id=key_id, resource=f"propose:{kind}",
            decision="allow",
            latency_ms=(time.monotonic() - t0) * 1000,
        )
        return result
    except AssistedActionError as exc:
        db.rollback()
        audit_record(
            user_id=uid, key_id=key_id, resource=f"propose:{kind}",
            decision="deny:invalid_proposal",
            latency_ms=(time.monotonic() - t0) * 1000,
        )
        raise ProposeError(str(exc)) from exc
    except Exception as exc:
        db.rollback()
        audit_record(
            user_id=uid, key_id=key_id, resource=f"propose:{kind}",
            decision="deny:data_error",
            latency_ms=(time.monotonic() - t0) * 1000,
        )
        raise ProposeError("Could not create the proposal.") from exc
    finally:
        db.close()
