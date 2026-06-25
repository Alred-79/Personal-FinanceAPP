"""Authentication service. Hardened around cookies and refresh tokens.

What changed from the bearer only version:
* Access tokens go out as ``httpOnly`` cookies, with a ``Bearer`` header
  fallback so Swagger ``/docs`` keeps working.
* Rotating refresh tokens are stored as SHA-256 hashes in the database.
* Signup now checks how strong the password is.
"""

import hashlib
from uuid import uuid4
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal, cast

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import RefreshToken as RefreshTokenORM
from server.src.db.models import User as UserORM
from server.src.db.session import get_db
from server.src.logging_context import set_user_id
from server.src.models import NewUser, TokenData, UserInDB
from server.src.services import token_keys
from server.src.settings import settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"

# The single, hardcoded demo account. The demo-login route is parameterless and
# only ever authenticates this username; the demo guards (plaid/users) key off it.
DEMO_USERNAME = "demo"

# Cap on how many active (un-revoked) refresh tokens the shared demo user may keep.
# Repeated "Enter the demo" taps would otherwise bloat the table indefinitely; we
# prune the oldest beyond this many so the demo user can't be used to farm rows.
DEMO_REFRESH_TOKEN_CAP = 20


def is_demo_user(user: Any) -> bool:
    """True when *user* is the shared demo account.

    Accepts anything carrying a ``username`` (a ``UserInDB`` or an ORM row). Used
    by the demo guards to block dangerous mutations (real-bank linking, password
    change) on the shared account so one visitor can't lock out or poison others.
    """
    return getattr(user, "username", None) == DEMO_USERNAME

# Keep the OAuth2 scheme so Swagger /docs can still inject a Bearer token.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/token/", auto_error=False)

# Password rules
_PASSWORD_MIN_LENGTH = 8
_PASSWORD_PATTERN = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^a-zA-Z0-9]).+$"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_access_token(access: str) -> dict:
    """Decode + verify a session access token (L3).

    New tokens are signed with the session HKDF key and carry ``aud="session"``.
    During the rollout grace window (``jwt_require_aud`` False) a legacy token —
    signed with the raw secret and lacking ``aud`` — is still accepted so logins
    issued before the deploy don't break; once those have expired, set
    ``jwt_require_aud=True`` to require the new form. Raises ``InvalidTokenError``
    (PyJWT) when neither path validates; the caller maps that to 401.
    """
    try:
        return token_keys.decode(
            access, purpose=token_keys.AUD_SESSION, audience=token_keys.AUD_SESSION
        )
    except jwt.PyJWTError:
        if settings.jwt_require_aud:
            raise  # grace window closed — only the new aud-bearing form is valid
        # Legacy fallback: pre-L3 access token (raw secret, no aud). Note this path
        # does NOT bind an audience, so the typ defense-in-depth check downstream
        # remains the cross-family guard for these old tokens until they expire.
        return jwt.decode(
            access, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )


def _to_user_in_db(user: Any) -> UserInDB:
    """Map an ORM User row to the pydantic UserInDB downstream routers expect."""
    return UserInDB(
        id=cast(int, user.id),
        username=cast(str, user.username),
        email=cast(str, user.email),
        full_name=cast(str, user.full_name),
        disabled=bool(user.disabled),
        spend_warning=cast(int, user.spend_warning),
        savings_percent=cast(int, user.savings_percent),
        hashed_password=cast(str, user.hashed_password),
        # Copy the real game_mode off the row. Omitting it let UserInDB fall back
        # to its "off" default, so /users/me/ always reported "off" regardless of
        # the stored value.
        game_mode=cast(str, getattr(user, "game_mode", "off")),
    )


def _hash_token(raw_token: str) -> str:
    """Return the SHA-256 hex digest of *raw_token*."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _utcnow() -> datetime:
    """A timezone aware UTC now, which avoids the deprecated ``datetime.utcnow()``."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class AuthService:
    def __init__(self) -> None:
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        self.SECRET_KEY = settings.jwt_secret_key
        self.ALGORITHM = settings.jwt_algorithm

    # -- password helpers ---------------------------------------------------

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return self.pwd_context.verify(plain_password, hashed_password)

    def get_password_hash(self, password: str) -> str:
        return self.pwd_context.hash(password)

    @staticmethod
    def validate_password_strength(password: str) -> None:
        """Raise 422 if *password* doesn't meet minimum complexity rules."""
        errors: list[str] = []
        if len(password) < _PASSWORD_MIN_LENGTH:
            errors.append(
                f"Password must be at least {_PASSWORD_MIN_LENGTH} characters."
            )
        if not _PASSWORD_PATTERN.match(password):
            errors.append(
                "Password must contain at least one uppercase letter, one "
                "lowercase letter, one digit, and one special character."
            )
        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=" ".join(errors),
            )

    # -- user CRUD ----------------------------------------------------------

    def get_user(self, db: Session, username: str) -> UserInDB | None:
        user = db.execute(
            select(UserORM).where(UserORM.username == username)
        ).scalar_one_or_none()
        if user:
            return _to_user_in_db(user)
        return None

    def create_user(self, db: Session, user: NewUser):
        self.validate_password_strength(user.password)

        hashed_password = self.get_password_hash(user.password)

        existing_username = db.execute(
            select(UserORM.id).where(UserORM.username == user.username)
        ).first()
        if existing_username:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Username already exists"
            )

        existing_email = db.execute(
            select(UserORM.id).where(UserORM.email == user.email)
        ).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
            )

        new_user = UserORM(
            username=user.username,
            full_name=user.full_name,
            email=user.email,
            disabled=0,
            hashed_password=hashed_password,
        )
        db.add(new_user)
        db.flush()  # assign PK / persist within the request transaction
        return self.authenticate_user(db, user.username, user.password)

    def authenticate_user(self, db: Session, username: str, password: str):
        user = self.get_user(db, username)
        if not user:
            return False
        if not self.verify_password(password, user.hashed_password):
            return False
        return user

    # -- JWT access tokens --------------------------------------------------

    def create_access_token(
        self, data: dict, expires_delta: timedelta | None = None
    ) -> str:
        to_encode = data.copy()
        expire = _utcnow() + (
            expires_delta
            or timedelta(minutes=settings.access_token_expire_minutes)
        )
        # ``jti`` makes every token unique even when two are minted within the
        # same second (same sub + same exp would otherwise collide byte for
        # byte, e.g. a login immediately followed by a refresh).
        to_encode.update({"exp": expire, "jti": uuid4().hex})
        # L3: sign session tokens with the session HKDF key + ``aud="session"`` so
        # they're isolated from the action/MCP families. ``token_keys.encode``
        # stamps ``aud``/``iss``. Legacy verification accepts the pre-L3 raw-secret
        # token during the grace window (see ``get_current_user``).
        return token_keys.encode(
            to_encode, purpose=token_keys.AUD_SESSION, audience=token_keys.AUD_SESSION
        )

    # -- Refresh tokens -----------------------------------------------------

    @staticmethod
    def create_refresh_token(db: Session, user_id: int) -> str:
        """Create a new refresh token, persist its hash, return the raw value."""
        raw = secrets.token_urlsafe(48)
        token_hash = _hash_token(raw)
        expires_at = _utcnow() + timedelta(days=settings.refresh_token_expire_days)

        row = RefreshTokenORM(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        db.add(row)
        db.flush()
        return raw

    @staticmethod
    def rotate_refresh_token(
        db: Session, raw_token: str
    ) -> tuple[str, UserInDB]:
        """Validate + revoke the old token and issue a fresh one.

        Returns ``(new_raw_token, user)``.
        Raises 401 if the token is invalid, expired, or already revoked.
        """
        token_hash = _hash_token(raw_token)
        row = db.execute(
            select(RefreshTokenORM).where(
                RefreshTokenORM.token_hash == token_hash
            )
        ).scalar_one_or_none()

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked refresh token",
            )
        if row.revoked:
            # Reusing a token that was already rotated is a sign of theft (RFC 6819
            # §5.2.2.3): revoke the whole family, so any session minted from this
            # lineage, including the one the attacker just rotated, dies too.
            # Commit right away so the revocation survives the 401's rollback.
            AuthService.revoke_all_user_tokens(db, cast(int, row.user_id))
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked refresh token",
            )
        if row.expires_at.replace(tzinfo=timezone.utc) < _utcnow():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token expired",
            )

        # Revoke the old token
        row.revoked = 1

        # Load the user
        user_orm = db.execute(
            select(UserORM).where(UserORM.id == row.user_id)
        ).scalar_one_or_none()
        if user_orm is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )

        # Issue a new refresh token
        new_raw = secrets.token_urlsafe(48)
        new_hash = _hash_token(new_raw)
        new_expires = _utcnow() + timedelta(days=settings.refresh_token_expire_days)
        db.add(
            RefreshTokenORM(
                user_id=row.user_id,
                token_hash=new_hash,
                expires_at=new_expires,
            )
        )
        db.flush()
        return new_raw, _to_user_in_db(user_orm)

    @staticmethod
    def revoke_refresh_token(db: Session, raw_token: str) -> None:
        """Mark a single refresh token as revoked (logout)."""
        token_hash = _hash_token(raw_token)
        row = db.execute(
            select(RefreshTokenORM).where(
                RefreshTokenORM.token_hash == token_hash
            )
        ).scalar_one_or_none()
        if row is not None:
            row.revoked = 1
            db.flush()

    @staticmethod
    def revoke_all_user_tokens(db: Session, user_id: int) -> None:
        """Revoke every active refresh token for a user (a full logout)."""
        rows = db.execute(
            select(RefreshTokenORM).where(
                RefreshTokenORM.user_id == user_id,
                RefreshTokenORM.revoked == 0,
            )
        ).scalars().all()
        for row in rows:
            row.revoked = 1
        db.flush()

    # -- Cookie helpers -----------------------------------------------------

    @staticmethod
    def prune_demo_refresh_tokens(
        db: Session, user_id: int, keep: int = DEMO_REFRESH_TOKEN_CAP
    ) -> None:
        """Revoke all but the newest *keep* active refresh tokens for *user_id*.

        The shared demo account is hit by every visitor, so repeated "Enter the
        demo" taps would otherwise grow its ``refresh_tokens`` rows without bound.
        Keeping only the newest N (by id, which is monotonic) bounds the table and
        leaves recent sessions intact. Called from the demo-login path only.
        """
        rows = db.execute(
            select(RefreshTokenORM)
            .where(
                RefreshTokenORM.user_id == user_id,
                RefreshTokenORM.revoked == 0,
            )
            .order_by(RefreshTokenORM.id.desc())
        ).scalars().all()
        for row in rows[keep:]:
            row.revoked = 1
        db.flush()

    @staticmethod
    def set_auth_cookies(
        response: Response,
        access_token: str,
        refresh_token: str,
        samesite: Literal["lax", "none", "strict"] = "lax",
    ) -> None:
        """Set httpOnly access + refresh cookies on *response*.

        *samesite* defaults to ``"lax"`` (the normal login path). The demo-login
        path passes ``"strict"`` to tighten the demo session's cross-site exposure.
        """
        secure = settings.cookie_secure
        domain = settings.cookie_domain

        response.set_cookie(
            key=ACCESS_COOKIE,
            value=access_token,
            httponly=True,
            secure=secure,
            samesite=samesite,
            path="/api",
            max_age=settings.access_token_expire_minutes * 60,
            domain=domain,
        )
        response.set_cookie(
            key=REFRESH_COOKIE,
            value=refresh_token,
            httponly=True,
            secure=secure,
            samesite=samesite,
            path="/api",  # scoped to /api so it reaches /api/refresh & /api/logout
            max_age=settings.refresh_token_expire_days * 86_400,
            domain=domain,
        )

    @staticmethod
    def clear_auth_cookies(response: Response) -> None:
        """Delete both auth cookies.

        Pass the SAME ``domain`` that ``set_auth_cookies`` used: when
        ``cookie_domain`` is configured, a delete_cookie without the matching
        domain targets a different cookie and logout silently fails to clear the
        real one. Mirroring the domain keeps logout effective in both
        cookie_domain-set and cookie_domain-unset deployments.
        """
        domain = settings.cookie_domain
        response.delete_cookie(key=ACCESS_COOKIE, path="/api", domain=domain)
        response.delete_cookie(key=REFRESH_COOKIE, path="/api", domain=domain)

    # -- Current user dependency --------------------------------------------

    @staticmethod
    async def get_current_user(
        request: Request,
        token: Annotated[str | None, Depends(oauth2_scheme)] = None,
        db: Session = Depends(get_db),
    ):
        """Pull the access token out of the request and check it.

        Lookup order:
        1. the ``access_token`` cookie (what the browser uses).
        2. the ``Authorization: Bearer …`` header (a fallback that keeps Swagger working).
        """
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

        # 1) Try the cookie first
        access = request.cookies.get(ACCESS_COOKIE)
        # 2) Fall back to the OAuth2 header token
        if not access:
            access = token
        if not access:
            raise credentials_exception

        try:
            payload = _decode_access_token(access)
            # Defense-in-depth (assessment P2): the access path is identified by
            # ``sub`` and historically ignored ``typ``. Reject any token carrying
            # a NON-access ``typ`` (an assistant-action or MCP-capability token)
            # so a confirm/capability token signed with the same secret can never
            # be replayed as a session credential, even if it gained a ``sub``.
            # Access tokens carry no ``typ`` (or, in future, "access").
            token_type = payload.get("typ")
            if token_type not in (None, "access"):
                raise credentials_exception
            username: str | None = payload.get("sub")
            if username is None:
                raise credentials_exception
            token_data = TokenData(username=username)
        except InvalidTokenError:
            raise credentials_exception

        user = db.execute(
            select(UserORM).where(UserORM.username == token_data.username)
        ).scalar_one_or_none()
        if user is None:
            raise credentials_exception
        # Stamp the resolved user into the request's logging context so every
        # downstream log line carries user=<id> (see server/src/logging_context).
        set_user_id(user.id)
        return _to_user_in_db(user)

    @staticmethod
    async def get_current_active_user(
        current_user: Annotated[UserInDB, Depends(get_current_user)]
    ):
        if current_user.disabled:
            raise HTTPException(status_code=400, detail="Inactive user")
        return current_user
