"""MCP key management REST API.

Endpoints are behind existing browser/session auth (AuthService.get_current_active_user),
NOT the MCP API key.  Raw key material is returned exactly once on creation and is
never stored or re-exposed.

UI copy: connecting an MCP client ships the user's full read data to that client.
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.src.db.session import get_db
from server.src.limiter import limiter
from server.src.models import UserInDB
from server.src.services.auth_service import AuthService
from server.src.services.mcp_key_service import MCPKeyService
from server.src.settings import settings

router = APIRouter(prefix="/mcp-keys", tags=["mcp-keys"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreateKeyRequest(BaseModel):
    name: str
    scopes: list[str]
    ttl_days: Optional[int] = None


class KeyMeta(BaseModel):
    id: int
    name: str
    key_prefix: str
    scopes: str
    created_at: Optional[str]
    last_used_at: Optional[str]
    expires_at: Optional[str]
    revoked: bool


class CreateKeyResponse(BaseModel):
    raw_key: str  # shown once; never stored
    id: int
    name: str
    key_prefix: str
    scopes: str
    expires_at: Optional[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/", response_model=CreateKeyResponse)
@limiter.limit(settings.mcp_key_rate_limit)
async def create_key(
    request: Request,
    body: CreateKeyRequest,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    """Create a new MCP API key.  The raw key is returned **once** — store it now."""
    try:
        raw, row = MCPKeyService.create(
            db, current_user.id, body.name, body.scopes, body.ttl_days
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    db.commit()
    return {
        "raw_key": raw,
        "id": row.id,
        "name": row.name,
        "key_prefix": row.key_prefix,
        "scopes": row.scopes,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


@router.get("/")
async def list_keys(
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    """List all API keys for the current user (prefixes only — never hashes or raw keys)."""
    return MCPKeyService.list_keys(db, current_user.id)


@router.delete("/{key_id}/")
async def revoke_key(
    key_id: int,
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    db: Session = Depends(get_db),
):
    """Revoke an API key immediately.  Subsequent requests using it will receive 401."""
    ok = MCPKeyService.revoke(db, current_user.id, key_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Key not found or does not belong to you.",
        )
    db.commit()
    return {"revoked": True, "id": key_id}
