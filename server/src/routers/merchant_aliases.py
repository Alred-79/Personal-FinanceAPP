"""Authenticated routes for reversible, user-confirmed merchant grouping."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.src.db.session import get_db
from server.src.models import UserInDB
from server.src.services.auth_service import AuthService
from server.src.services.merchant_identity_service import (
    MerchantAliasError,
    MerchantIdentityService,
)
from server.src.settings import settings


def _enabled() -> None:
    if not settings.merchant_aliases_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


router = APIRouter(
    prefix="/merchant-aliases",
    tags=["merchant-aliases"],
    dependencies=[Depends(_enabled)],
)


class MerchantAliasCreate(BaseModel):
    alias_descriptor: str = Field(min_length=1, max_length=500)
    canonical_descriptor: str = Field(min_length=1, max_length=500)
    confirmed: Literal[True]


class MerchantAliasResponse(BaseModel):
    id: int
    alias_key: str
    canonical_key: str
    canonical_label: str
    source: Literal["user"]
    active: bool
    created_at: datetime | None = None


class MerchantDescriptorResponse(BaseModel):
    descriptor: str
    normalized_key: str


@router.get("/", response_model=list[MerchantAliasResponse])
def list_aliases(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    return MerchantIdentityService(db).list_aliases(current_user.id)


@router.get("/descriptors/", response_model=list[MerchantDescriptorResponse])
def list_descriptors(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=100),
):
    return MerchantIdentityService(db).descriptors(current_user.id, limit=limit)


@router.post(
    "/", response_model=MerchantAliasResponse, status_code=status.HTTP_201_CREATED
)
def create_alias(
    payload: MerchantAliasCreate,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    try:
        return MerchantIdentityService(db).confirm(
            current_user.id,
            payload.alias_descriptor,
            payload.canonical_descriptor,
        )
    except MerchantAliasError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{alias_id}/", status_code=status.HTTP_204_NO_CONTENT)
def revert_alias(
    alias_id: int,
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    if not MerchantIdentityService(db).revert(current_user.id, alias_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return None
