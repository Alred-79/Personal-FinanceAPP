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
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typing import Annotated

from server.src.db.models import User as UserORM
from server.src.db.session import get_db
from server.src.models import NewUser, Token
from server.src.limiter import limiter
from server.src.services.auth_service import (
    DEMO_USERNAME,
    REFRESH_COOKIE,
    AuthService,
)
from server.src.settings import settings
from server.src.services.demo_readiness import assess_demo_readiness

router = APIRouter()
auth_service = AuthService()


def _require_demo_enabled() -> None:
    """404 the demo routes when the flag is off, so the feature does not exist.

    Evaluated as a ``Depends`` guard BEFORE either handler body runs. Read fresh
    from the settings singleton each request so monkeypatching ``demo_mode_enabled``
    in tests reaches it (mirrors the ``_require_enabled`` pattern in tax.py).
    """
    if not settings.demo_mode_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        )


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

    # The refresh token is delivered ONLY via the httpOnly cookie (set above).
    # Never echo it in the JSON body: a body field is readable by JavaScript and
    # therefore by any XSS payload, which would defeat the httpOnly design. The
    # access token stays in the body so the SPA can use a Bearer header / Swagger
    # /docs keeps working.
    return Token(
        access_token=access_token,
        token_type="bearer",
    )


@router.post("/signup/")
@limiter.limit(settings.signup_rate_limit)
async def signup(
    request: Request,
    response: Response,
    user: NewUser,
    db: Session = Depends(get_db),
):
    # Registration guard (Step 01). Runs FIRST so a doomed second signup never
    # reaches password hashing (defends the bcrypt-CPU enumeration angle before
    # Step 02's limiter exists). Read fresh from the settings singleton each
    # request, so monkeypatching settings.single_user in tests reaches it.
    if not settings.allow_signup:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is disabled.",
        )
    if settings.single_user:
        existing = db.execute(select(func.count(UserORM.id))).scalar_one()
        if existing >= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Registration is closed (single-user instance).",
            )

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

    # Refresh token stays in the httpOnly cookie only — never in the JSON body.
    return Token(
        access_token=access_token,
        token_type="bearer",
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

    # Rotated refresh token stays in the httpOnly cookie only — never echoed.
    return Token(
        access_token=new_access,
        token_type="bearer",
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


# ---------------------------------------------------------------------------
# Demo mode (gated by settings.demo_mode_enabled; see docs/DEMO-MODE.md)
# ---------------------------------------------------------------------------


@router.get("/capabilities/")
async def public_capabilities(db: Session = Depends(get_db)):
    """Public instance availability, without exposing provider credentials.

    Logged-out and first-run clients use this to avoid presenting controls that
    are guaranteed to fail (closed registration, unconfigured bank/AI tools).
    """
    existing_users = db.execute(select(func.count(UserORM.id))).scalar_one()
    registration_open = settings.allow_signup and (
        not settings.single_user or existing_users == 0
    )
    return {
        "registration_open": registration_open,
        "demo": settings.demo_mode_enabled,
        "plaid": bool(settings.plaid_client_id and settings.plaid_client_secret),
        "assistant": bool(settings.groq_api_key),
        "web_search": bool(settings.tavily_api_key) and not settings.egress_disabled,
        "unstructured_import": bool(settings.groq_api_key),
    }


@router.get("/demo-status/")
async def demo_status(db: Session = Depends(get_db)):
    """Public. Tells the logged-out UI whether to show the "Enter the demo" button.

    Leaks nothing beyond the boolean flag value (which is observable anyway from
    whether demo-login 404s). NOT gated — it must answer ``false`` when off.
    """
    readiness = assess_demo_readiness(db, enabled=settings.demo_mode_enabled)
    return {
        "enabled": settings.demo_mode_enabled,
        "ready": readiness.ready,
        "state": readiness.state,
        "reason_code": readiness.reason_code,
    }


@router.post("/demo-login/", dependencies=[Depends(_require_demo_enabled)])
@limiter.limit(settings.login_rate_limit)
async def demo_login(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> Token:
    """Parameterless login into the single hardcoded ``demo`` user.

    This is NOT a password backdoor: it takes NO username/password input (nothing
    to enumerate or stuff), 404s when the flag is off, and only ever loads the
    fixed ``demo`` account via the same hardened machinery as ``/token/``. The demo
    user is an ordinary ``disabled=0`` user, so every downstream request still flows
    auth → get_current_active_user → RLS and can only ever see the demo user's rows.

    Per-IP rate-limited (inherits ``login_rate_limit``); the demo user's refresh
    tokens are pruned/capped so repeated taps can't bloat the table; cookies use
    ``SameSite=Strict`` to tighten the shared session's cross-site exposure.
    """
    readiness = assess_demo_readiness(db, enabled=True)
    if not readiness.ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "The demo is being prepared. Please try again shortly.",
                "reason_code": readiness.reason_code,
            },
        )
    user = auth_service.get_user(db, DEMO_USERNAME)
    # Readiness proved this row exists; keep the guard for type-checking and a
    # concurrent operator teardown between the two read-only queries.
    if user is None:
        raise HTTPException(status_code=503, detail="Demo account unavailable.")
    if user.disabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo account is disabled.",
        )

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = auth_service.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    refresh_token = auth_service.create_refresh_token(db, user.id)
    # Bound the shared account's refresh-token rows (prune oldest beyond the cap).
    auth_service.prune_demo_refresh_tokens(db, user.id)

    auth_service.set_auth_cookies(
        response, access_token, refresh_token, samesite="strict"
    )

    # Refresh token stays in the httpOnly cookie only — never echoed in the body.
    return Token(access_token=access_token, token_type="bearer")
