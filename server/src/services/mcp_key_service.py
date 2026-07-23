"""MCP API-key service — create / list / revoke / resolve.

All key material is handled through SHA-256 hashes; the raw key is returned
exactly once from ``create`` and is **never** stored or logged anywhere.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import MCPKey, User as UserORM
from server.src.mcp.principal import Principal
from server.src.mcp.scopes import normalize_scopes
from server.src.settings import settings

log = logging.getLogger(__name__)

# Reuse the same SHA-256 approach as auth_service._hash_token.  We inline it
# here to keep the module self-contained and avoid a circular import.
_KEY_PREFIX_LEN = 12
_KEY_FORMAT_PREFIX = "bdgt_live_"
_LAST_USED_THROTTLE_SECONDS = 300  # 5 minutes — avoid a write per request


def _hash_key(raw: str) -> str:
    """Return the SHA-256 hex digest of *raw*."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MCPKeyService:
    """Stateless service — every method takes a ``db`` session explicitly."""

    # ------------------------------------------------------------------
    # create
    # ------------------------------------------------------------------
    @staticmethod
    def create(
        db: Session,
        user_id: int,
        name: str,
        scopes: list[str],
        ttl_days: int = 90,
    ) -> tuple[str, MCPKey]:
        """Mint a new MCP API key.

        Returns ``(raw_key, mcp_key_row)``.  The raw key is shown to the
        caller **once** — it is never persisted.

        Raises ``ValueError`` for empty or invalid scopes.
        """
        if isinstance(ttl_days, bool) or not isinstance(ttl_days, int):
            raise ValueError("ttl_days must be a whole number from 1 through 365.")
        if ttl_days < 1 or ttl_days > 365:
            raise ValueError("ttl_days must be from 1 through 365.")

        # -- validate scopes --
        if not scopes:
            raise ValueError("At least one scope is required.")
        allowed = set(settings.mcp_allowed_scopes)
        # The propose-only write scope is mintable ONLY when the feature is on, so
        # a default (feature-off) deployment can't even create a propose-capable
        # key. See the note on settings.mcp_allowed_scopes.
        if settings.mcp_propose_enabled:
            allowed.add("propose:actions")
        unknown = set(scopes) - allowed
        if unknown:
            raise ValueError(
                f"Unknown scope(s): {', '.join(sorted(unknown))}. "
                f"Allowed: {', '.join(sorted(allowed))}"
            )

        # Normalize legacy <resource>:read scopes to the modern read:<resource>
        # form that the tools actually check, dropping write/chat scopes that
        # grant no MCP read tool. A key left with no usable scope is rejected.
        stored_scopes = normalize_scopes(scopes)
        if not stored_scopes:
            raise ValueError(
                "None of the requested scopes grant access to an MCP read tool. "
                "Use read:accounts, read:transactions, read:goals, read:budgets, "
                "or read:context."
            )

        raw = _KEY_FORMAT_PREFIX + secrets.token_urlsafe(32)
        key_hash = _hash_key(raw)
        key_prefix = raw[:_KEY_PREFIX_LEN]

        expires_at = _utcnow() + timedelta(days=ttl_days)

        row = MCPKey(
            user_id=user_id,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes=",".join(stored_scopes),
            expires_at=expires_at,
        )
        db.add(row)
        db.flush()
        return raw, row

    # ------------------------------------------------------------------
    # list
    # ------------------------------------------------------------------
    @staticmethod
    def list_keys(db: Session, user_id: int) -> list[dict]:
        """Return metadata for all keys owned by *user_id*.

        **Never** includes ``key_hash`` or the raw key.
        """
        rows = (
            db.execute(
                select(MCPKey).where(MCPKey.user_id == user_id)
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": r.id,
                "name": r.name,
                "key_prefix": r.key_prefix,
                "scopes": r.scopes,
                "created_at": r.created_at,
                "last_used_at": r.last_used_at,
                "expires_at": r.expires_at,
                "revoked": bool(r.revoked),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # revoke
    # ------------------------------------------------------------------
    @staticmethod
    def revoke(db: Session, user_id: int, key_id: int) -> bool:
        """Revoke a key by id, scoped to the owning user.

        Returns ``True`` if the key was found and belongs to *user_id*,
        ``False`` otherwise (including cross-user attempts).  Revoking an
        already-revoked key is a no-op that still returns ``True``.
        """
        row = db.execute(
            select(MCPKey).where(MCPKey.id == key_id, MCPKey.user_id == user_id)
        ).scalar_one_or_none()
        if row is None:
            return False
        if not row.revoked:
            row.revoked = 1
            row.revoked_at = _utcnow()
            db.flush()
        return True

    # ------------------------------------------------------------------
    # resolve
    # ------------------------------------------------------------------
    @staticmethod
    def resolve(db: Session, raw_key: str) -> Optional[Principal]:
        """Look up *raw_key* by its hash and return a ``Principal``.

        Returns ``None`` (never raises) if the key is unknown, revoked,
        or expired — the caller maps ``None`` to a clean 401.

        ``last_used_at`` is updated in-place but **throttled**: we only
        write if the current value is stale by ≥ ``_LAST_USED_THROTTLE_SECONDS``
        to avoid a DB write on every single request.
        """
        key_hash = _hash_key(raw_key)
        row = db.execute(
            select(MCPKey).where(MCPKey.key_hash == key_hash)
        ).scalar_one_or_none()

        if row is None:
            return None
        if row.revoked:
            return None
        if row.expires_at is not None:
            expires = row.expires_at
            # SQLite stores naive datetimes; treat them as UTC.
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires < _utcnow():
                return None

        # Load the user to make sure they still exist AND are not disabled.
        # A disabled account (the owner locked themselves out, or an admin
        # revoked them) must lose MCP access on the very next request, even
        # mid-session — there is no cached session principal to keep them
        # alive once the stateless transport is on. We return ``None`` (not a
        # distinct error) so the middleware's deny message stays opaque and a
        # probing caller can't tell "disabled" apart from "unknown/expired".
        user = db.execute(
            select(UserORM).where(UserORM.id == row.user_id)
        ).scalar_one_or_none()
        if user is None or user.disabled:
            return None

        # Throttled last_used_at update.
        now = _utcnow()
        if row.last_used_at is None or (
            now - row.last_used_at.replace(tzinfo=timezone.utc)
        ).total_seconds() >= _LAST_USED_THROTTLE_SECONDS:
            row.last_used_at = now
            db.flush()

        # Normalize stored scopes so already-issued legacy keys (e.g. created
        # before the modern read:* form) resolve to scopes the tools recognize.
        scopes = (
            frozenset(normalize_scopes(row.scopes.split(",")))
            if row.scopes
            else frozenset()
        )
        return Principal(user_id=row.user_id, key_id=row.id, scopes=scopes)
