"""Auth router. Hardened around cookies and refresh tokens.

Endpoints:
* ``POST /token/``   logs in and sets httpOnly cookies
* ``POST /signup/``  registers, logs in right away, and sets httpOnly cookies
* ``POST /refresh/`` rotates the refresh token and hands back a new cookie pair
* ``POST /logout/``  revokes the refresh token and clears the cookies
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import Annotated

from server.src.db.session import get_db
from server.src.models import NewUser, Token
from server.src.limiter import limiter
from server.src.services.auth_service import (
    REFRESH_COOKIE,
    AuthService,
)
from server.src.settings import settings

router = APIRouter()
auth_service = AuthService()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/token/")
@limiter.limit(settings.login_rate_limit)
async def login_for_access_token(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(get_db),
) -> Token:
    user = auth_service.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = auth_service.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    refresh_token = auth_service.create_refresh_token(db, user.id)

    auth_service.set_auth_cookies(response, access_token, refresh_token)

    return Token(
        access_token=access_token,
        token_type="bearer",
        refresh_token=refresh_token,
    )


@router.post("/signup/")
async def signup(
    request: Request,
    response: Response,
    user: NewUser,
    db: Session = Depends(get_db),
):
    authed_user = auth_service.create_user(db, user)
    if not authed_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to create user",
        )

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = auth_service.create_access_token(
        data={"sub": authed_user.username}, expires_delta=access_token_expires
    )
    refresh_token = auth_service.create_refresh_token(db, authed_user.id)

    auth_service.set_auth_cookies(response, access_token, refresh_token)

    return Token(
        access_token=access_token,
        token_type="bearer",
        refresh_token=refresh_token,
    )


@router.post("/refresh/")
@limiter.limit(settings.refresh_rate_limit)
async def refresh_tokens(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Rotate the refresh token and issue a fresh access + refresh cookie pair."""
    raw_refresh = request.cookies.get(REFRESH_COOKIE)
    if not raw_refresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
        )

    new_raw_refresh, user = auth_service.rotate_refresh_token(db, raw_refresh)

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    new_access = auth_service.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    auth_service.set_auth_cookies(response, new_access, new_raw_refresh)

    return Token(
        access_token=new_access,
        token_type="bearer",
        refresh_token=new_raw_refresh,
    )


@router.post("/logout/")
async def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Revoke the refresh token and clear auth cookies."""
    raw_refresh = request.cookies.get(REFRESH_COOKIE)
    if raw_refresh:
        auth_service.revoke_refresh_token(db, raw_refresh)

    auth_service.clear_auth_cookies(response)
    return {"detail": "Logged out"}
