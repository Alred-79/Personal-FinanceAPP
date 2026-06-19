"""Tests for the MCP server surface.

Coverage:
* Auth middleware — missing key, garbage key, valid key, revoked key, query-string token.
* Tool dispatching — correct vault resource called; scope enforcement (wrong scope → error).
* Feature flag — mcp_enabled=False ships dark by default.

Strategy:
- HTTP-layer tests use a minimal Starlette app that has only MCPAuthMiddleware + a
  trivial echo route.  This avoids needing a live MCP session manager for the auth tests.
- Tool tests use the fastmcp in-process Client(mcp) with the principal ContextVar set
  manually and vault.read patched so no real DB is needed.
"""

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from server.src.db.models import MCPKey, User as UserORM
from server.src.mcp.principal import Principal
from server.src.mcp.server import MCPAuthMiddleware, _current_principal, get_principal
from server.src.services.mcp_key_service import MCPKeyService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db, username="alice"):
    from passlib.context import CryptContext
    ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    user = UserORM(
        username=username,
        email=f"{username}@example.com",
        full_name=username.title(),
        hashed_password=ctx.hash("Password1!"),
        disabled=False,
        spend_warning=80,
        savings_percent=20,
    )
    db.add(user)
    db.flush()
    return user


class _NoClose:
    """Prevent the middleware from closing the shared test session."""
    def __init__(self, s):
        self._s = s

    def __getattr__(self, name):
        return getattr(self._s, name)

    def close(self):
        pass


def _make_echo_app(db_session):
    """Minimal Starlette app with MCPAuthMiddleware for HTTP-layer tests."""
    async def echo(request: Request):
        p = _current_principal.get()
        return JSONResponse({"principal_user_id": p.user_id if p else None})

    return Starlette(
        routes=[Route("/{path:path}", echo)],
        middleware=[
            Middleware(
                MCPAuthMiddleware,
                db_factory=lambda: _NoClose(db_session),
            )
        ],
    )


# ---------------------------------------------------------------------------
# Auth middleware tests (HTTP layer)
# ---------------------------------------------------------------------------

class TestAuthMiddleware:
    def test_no_auth_header_returns_401(self, db_session):
        app = _make_echo_app(db_session)
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/")
        assert r.status_code == 401
        assert "WWW-Authenticate" in r.headers

    def test_wrong_scheme_returns_401(self, db_session):
        app = _make_echo_app(db_session)
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/", headers={"Authorization": "Basic abc123"})
        assert r.status_code == 401

    def test_garbage_bearer_returns_401(self, db_session):
        app = _make_echo_app(db_session)
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/", headers={"Authorization": "Bearer not_a_real_key"})
        assert r.status_code == 401
        assert "WWW-Authenticate" in r.headers

    def test_valid_key_passes_through(self, db_session):
        user = _make_user(db_session)
        raw, _ = MCPKeyService.create(
            db_session, user.id, "test-key", ["read:accounts"]
        )
        db_session.commit()

        app = _make_echo_app(db_session)
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/", headers={"Authorization": f"Bearer {raw}"})
        assert r.status_code == 200
        assert r.json()["principal_user_id"] == user.id

    def test_revoked_key_returns_401(self, db_session):
        user = _make_user(db_session)
        raw, row = MCPKeyService.create(
            db_session, user.id, "will-revoke", ["read:accounts"]
        )
        MCPKeyService.revoke(db_session, user.id, row.id)
        db_session.commit()

        app = _make_echo_app(db_session)
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/", headers={"Authorization": f"Bearer {raw}"})
        assert r.status_code == 401

    def test_token_in_query_string_rejected(self, db_session):
        """Bearer tokens in the query string are ignored — header-only enforced."""
        user = _make_user(db_session)
        raw, _ = MCPKeyService.create(
            db_session, user.id, "qs-key", ["read:accounts"]
        )
        db_session.commit()

        app = _make_echo_app(db_session)
        with TestClient(app, raise_server_exceptions=False) as client:
            # Key is in query string, not header
            r = client.get(f"/?token={raw}")
        assert r.status_code == 401
        # The body explains the mistake instead of a bare "Unauthorized".
        assert "query string" in r.text.lower()
        assert "authorization" in r.text.lower()

    def test_missing_header_message_distinct_from_rejected_key(self, db_session):
        """Missing-credentials and bad-key 401s carry different, non-leaky bodies."""
        user = _make_user(db_session)
        raw, _ = MCPKeyService.create(db_session, user.id, "k", ["read:accounts"])
        db_session.commit()
        app = _make_echo_app(db_session)
        with TestClient(app, raise_server_exceptions=False) as client:
            missing = client.get("/")
            rejected = client.get("/", headers={"Authorization": "Bearer wrong"})
        assert missing.status_code == rejected.status_code == 401
        assert "missing" in missing.text.lower()
        assert "rejected" in rejected.text.lower()
        assert missing.text != rejected.text

    def test_www_authenticate_present_on_401(self, db_session):
        app = _make_echo_app(db_session)
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/")
        assert "WWW-Authenticate" in r.headers
        assert "Bearer" in r.headers["WWW-Authenticate"]


# ---------------------------------------------------------------------------
# Tool dispatch tests (in-process, vault.read patched)
# ---------------------------------------------------------------------------

class TestToolDispatch:
    @pytest.mark.asyncio
    async def test_get_accounts_calls_vault_accounts(self, monkeypatch):
        """get_accounts routes to vault resource 'accounts'."""
        from fastmcp import Client
        import server.src.mcp.vault as vault_mod

        calls = []

        def fake_read(cap_token, resource, **params):
            calls.append((resource, params))
            return [{"id": 1, "name": "Checking", "balance": 100.0}]

        monkeypatch.setattr(vault_mod, "read", fake_read)

        principal = Principal(user_id=7, key_id=1, scopes=frozenset(["read:accounts"]))
        tok = _current_principal.set(principal)
        try:
            from server.src.mcp.server import mcp
            async with Client(mcp) as client:
                result = await client.call_tool_mcp("get_accounts", {})
        finally:
            _current_principal.reset(tok)

        assert not result.isError
        assert calls == [("accounts", {})]

    @pytest.mark.asyncio
    async def test_get_accounts_wrong_scope_is_error(self, monkeypatch):
        """A principal without read:accounts gets an error response, not an exception."""
        from fastmcp import Client
        import server.src.mcp.vault as vault_mod

        monkeypatch.setattr(vault_mod, "read", lambda *a, **kw: [])

        principal = Principal(user_id=7, key_id=1, scopes=frozenset(["read:transactions"]))
        tok = _current_principal.set(principal)
        try:
            from server.src.mcp.server import mcp
            async with Client(mcp) as client:
                result = await client.call_tool_mcp("get_accounts", {})
        finally:
            _current_principal.reset(tok)

        assert result.isError

    @pytest.mark.asyncio
    async def test_get_transactions_by_date_range_routes_correctly(self, monkeypatch):
        from fastmcp import Client
        import server.src.mcp.vault as vault_mod

        calls = []

        def fake_read(cap_token, resource, **params):
            calls.append((resource, params))
            return {"items": [], "has_more": False, "next_offset": None}

        monkeypatch.setattr(vault_mod, "read", fake_read)

        principal = Principal(user_id=7, key_id=1, scopes=frozenset(["read:transactions"]))
        tok = _current_principal.set(principal)
        try:
            from server.src.mcp.server import mcp
            async with Client(mcp) as client:
                result = await client.call_tool_mcp(
                    "get_transactions_by_date_range",
                    {"start": "2025-01-01", "end": "2025-01-31"},
                )
        finally:
            _current_principal.reset(tok)

        assert not result.isError
        assert calls[0][0] == "tx_by_date"
        assert calls[0][1] == {
            "start": "2025-01-01",
            "end": "2025-01-31",
            "limit": 200,
            "offset": 0,
        }

    @pytest.mark.asyncio
    async def test_get_goals_routes_correctly(self, monkeypatch):
        from fastmcp import Client
        import server.src.mcp.vault as vault_mod

        calls = []
        monkeypatch.setattr(vault_mod, "read", lambda cap, res, **p: calls.append(res) or [])

        principal = Principal(user_id=7, key_id=1, scopes=frozenset(["read:goals"]))
        tok = _current_principal.set(principal)
        try:
            from server.src.mcp.server import mcp
            async with Client(mcp) as client:
                result = await client.call_tool_mcp("get_goals", {})
        finally:
            _current_principal.reset(tok)

        assert not result.isError
        assert calls == ["goals"]

    @pytest.mark.asyncio
    async def test_get_budgets_routes_correctly(self, monkeypatch):
        from fastmcp import Client
        import server.src.mcp.vault as vault_mod

        calls = []
        monkeypatch.setattr(vault_mod, "read", lambda cap, res, **p: calls.append(res) or [])

        principal = Principal(user_id=7, key_id=1, scopes=frozenset(["read:budgets"]))
        tok = _current_principal.set(principal)
        try:
            from server.src.mcp.server import mcp
            async with Client(mcp) as client:
                result = await client.call_tool_mcp("get_budgets", {})
        finally:
            _current_principal.reset(tok)

        assert not result.isError
        assert calls == ["budgets"]

    @pytest.mark.asyncio
    async def test_get_spend_summary_routes_correctly(self, monkeypatch):
        from fastmcp import Client
        import server.src.mcp.vault as vault_mod

        calls = []
        monkeypatch.setattr(vault_mod, "read", lambda cap, res, **p: calls.append(res) or {})

        principal = Principal(user_id=7, key_id=1, scopes=frozenset(["read:budgets"]))
        tok = _current_principal.set(principal)
        try:
            from server.src.mcp.server import mcp
            async with Client(mcp) as client:
                result = await client.call_tool_mcp("get_spend_summary", {})
        finally:
            _current_principal.reset(tok)

        assert not result.isError
        assert calls == ["spend_summary"]

    @pytest.mark.asyncio
    async def test_user_id_comes_from_principal_not_args(self, monkeypatch):
        """user_id in the capability token must match the principal — never a tool arg."""
        from fastmcp import Client
        import server.src.mcp.vault as vault_mod
        from server.src.services import token_keys

        seen_uid = []

        def fake_read(cap_token, resource, **params):
            # L3: capability tokens are signed with the MCP HKDF key + aud, so
            # decode with the MCP purpose (not the raw secret).
            payload = token_keys.decode(
                cap_token, purpose=token_keys.AUD_MCP, audience=token_keys.AUD_MCP
            )
            seen_uid.append(int(payload["uid"]))
            return []

        monkeypatch.setattr(vault_mod, "read", fake_read)

        principal = Principal(user_id=42, key_id=1, scopes=frozenset(["read:accounts"]))
        tok = _current_principal.set(principal)
        try:
            from server.src.mcp.server import mcp
            async with Client(mcp) as client:
                await client.call_tool_mcp("get_accounts", {})
        finally:
            _current_principal.reset(tok)

        assert seen_uid == [42]


# ---------------------------------------------------------------------------
# Feature flag test
# ---------------------------------------------------------------------------

class TestFeatureFlag:
    def test_mcp_enabled_is_false_by_default(self):
        """MCP surface ships dark — mcp_enabled must be False unless explicitly set."""
        from server.src.settings import settings
        assert not settings.mcp_enabled, (
            "mcp_enabled must default to False so /mcp is not exposed without opt-in"
        )

    def test_get_principal_raises_without_middleware(self):
        """get_principal() raises RuntimeError outside an authenticated request."""
        tok = _current_principal.set(None)
        try:
            with pytest.raises(RuntimeError, match="No principal in context"):
                get_principal()
        finally:
            _current_principal.reset(tok)
