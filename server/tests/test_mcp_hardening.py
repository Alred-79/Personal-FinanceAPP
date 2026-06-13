"""Step 05 — C2 MCP hardening tests.

Covers the defense-in-depth fixes layered onto the MCP auth boundary:

* Disabled users lose access on the next request, with the deny message kept
  opaque (no "disabled" leak).
* The app is built with the stateless HTTP transport (no session principal
  frozen at session creation), and the middleware binds ``scope["user"]`` per
  request.
* A pre-auth IP throttle sheds a flood of bad keys BEFORE any DB query (the
  ``resolve`` call / db_factory is never invoked) and returns 429 with a
  preserved ``Retry-After`` header.
* Auth failures (unknown key) and per-key rate-limit hits are audited with the
  real reason for the owner, even though the caller's message stays opaque.

The HTTP-layer tests drive ``MCPAuthMiddleware`` directly over a crafted ASGI
scope (mirroring test_mcp_failure_modes.py) so no live MCP session is needed.
"""

import json

import anyio

from server.src.db.models import User as UserORM
from server.src.mcp import server as srv
from server.src.mcp.server import (
    MCPAuthMiddleware,
    _current_principal,
    reset_preauth_throttle,
    reset_rate_limiter,
)
from server.src.services.mcp_key_service import MCPKeyService
from server.src.settings import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user(db, uid=1, username="alice", email="a@x.com", disabled=0):
    u = UserORM(
        id=uid,
        username=username,
        full_name="Test",
        email=email,
        hashed_password="x",
        disabled=disabled,
        savings_percent=0,
        spend_warning=20,
    )
    db.add(u)
    db.flush()
    return u


class _NoClose:
    """Stop the code-under-test from closing the shared test session."""

    def __init__(self, s):
        self._s = s

    def __getattr__(self, name):
        return getattr(self._s, name)

    def close(self):
        pass


class _NullDb:
    """A no-op DB session for tests where ``resolve`` is monkeypatched and the
    real session is irrelevant — commit/close are no-ops so the middleware's
    ``db.commit()`` / ``db.close()`` don't fail against a missing session."""

    def commit(self):
        pass

    def close(self):
        pass


def _run_middleware(headers, db_factory, *, client=("203.0.113.7", 5555)):
    """Drive MCPAuthMiddleware once with a crafted ASGI scope.

    Returns (status_code, principal_seen_by_app_or_None, app_called_bool,
    scope_user_seen). ``client`` populates ``scope["client"]`` so the proxy-aware
    pre-auth key has a peer address to bucket on.
    """
    seen = {"principal": None, "app_called": False, "scope_user": None}

    async def app(scope, receive, send):
        seen["app_called"] = True
        seen["principal"] = _current_principal.get()
        seen["scope_user"] = scope.get("user")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = MCPAuthMiddleware(app, db_factory=db_factory)
    status = {}
    resp_headers = {}

    async def send(msg):
        if msg["type"] == "http.response.start":
            status["code"] = msg["status"]
            resp_headers.update(
                {k.decode("latin-1").lower(): v.decode("latin-1")
                 for k, v in msg.get("headers", [])}
            )

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp/",
        "headers": headers,
        "client": client,
        "query_string": b"",
    }
    anyio.run(mw.__call__, scope, receive, send)
    return status.get("code"), seen["principal"], seen["app_called"], resp_headers, seen["scope_user"]


# ---------------------------------------------------------------------------
# Disabled users
# ---------------------------------------------------------------------------

class TestDisabledUserDenied:
    def test_disabled_user_denied(self, db_session):
        """A valid key whose owner is disabled → 401, and no tool/app runs."""
        user = _user(db_session, uid=1, disabled=1)
        raw, _row = MCPKeyService.create(
            db_session, user.id, "k", ["read:accounts"]
        )
        db_session.commit()

        code, principal, app_called, _hdrs, _su = _run_middleware(
            [(b"authorization", f"Bearer {raw}".encode())],
            lambda: _NoClose(db_session),
        )
        assert code == 401
        assert principal is None
        assert app_called is False

    def test_disabled_deny_message_stays_opaque(self, db_session):
        """The deny body must not reveal 'disabled' — same opaque text as a
        revoked/unknown key, so a probing caller learns nothing."""
        user = _user(db_session, uid=1, disabled=1)
        raw, _row = MCPKeyService.create(
            db_session, user.id, "k", ["read:accounts"]
        )
        db_session.commit()

        # Capture the actual response body via a richer harness.
        body = {}

        async def app(scope, receive, send):  # should never run
            body["app_ran"] = True

        mw = MCPAuthMiddleware(app, db_factory=lambda: _NoClose(db_session))
        chunks = []

        async def send(msg):
            if msg["type"] == "http.response.body":
                chunks.append(msg.get("body", b""))

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        scope = {
            "type": "http", "method": "POST", "path": "/mcp/",
            "headers": [(b"authorization", f"Bearer {raw}".encode())],
            "client": ("203.0.113.7", 1), "query_string": b"",
        }
        anyio.run(mw.__call__, scope, receive, send)
        text = b"".join(chunks).decode("latin-1").lower()
        assert "disabled" not in text
        assert "rejected" in text
        assert not body.get("app_ran")

    def test_enabled_user_still_passes(self, db_session):
        """Control: a non-disabled owner with the same key shape passes."""
        user = _user(db_session, uid=1, disabled=0)
        raw, _row = MCPKeyService.create(
            db_session, user.id, "k", ["read:accounts"]
        )
        db_session.commit()

        code, principal, app_called, _h, scope_user = _run_middleware(
            [(b"authorization", f"Bearer {raw}".encode())],
            lambda: _NoClose(db_session),
        )
        assert code == 200
        assert principal is not None and principal.user_id == user.id
        assert app_called is True
        # scope["user"] is bound to the same re-resolved principal (defense-in-depth).
        assert scope_user is not None and scope_user.user_id == user.id


# ---------------------------------------------------------------------------
# Stateless transport + scope["user"]
# ---------------------------------------------------------------------------

class TestStatelessHttp:
    def test_stateless_http_enabled(self):
        """build_mcp_starlette constructs the app with stateless transport."""
        captured = {}

        # Inspect the kwargs passed to FastMCP.http_app.
        orig = srv.mcp.http_app

        def spy(*args, **kwargs):
            captured.update(kwargs)
            return orig(*args, **kwargs)

        srv.mcp.http_app = spy
        try:
            srv.build_mcp_starlette(db_factory=lambda: None)
        finally:
            srv.mcp.http_app = orig

        assert captured.get("stateless_http") is True

    def test_two_requests_different_keys_never_share_principal(self, db_session):
        """Behavioural: two requests with different keys each see their own
        principal — no session principal frozen across requests."""
        u1 = _user(db_session, uid=1, username="alice", email="a@x.com")
        u2 = _user(db_session, uid=2, username="bob", email="b@x.com")
        raw1, _ = MCPKeyService.create(db_session, u1.id, "k1", ["read:accounts"])
        raw2, _ = MCPKeyService.create(db_session, u2.id, "k2", ["read:accounts"])
        db_session.commit()

        factory = lambda: _NoClose(db_session)
        _c1, p1, _a1, _h1, su1 = _run_middleware(
            [(b"authorization", f"Bearer {raw1}".encode())], factory)
        _c2, p2, _a2, _h2, su2 = _run_middleware(
            [(b"authorization", f"Bearer {raw2}".encode())], factory)
        assert p1.user_id == 1 and p2.user_id == 2
        assert su1.user_id == 1 and su2.user_id == 2

    def test_scope_user_bound_per_request(self, db_session):
        """scope['user'] is set to the resolved principal (always — independent
        of the transport flag)."""
        user = _user(db_session, uid=1)
        raw, _ = MCPKeyService.create(db_session, user.id, "k", ["read:accounts"])
        db_session.commit()

        _c, _p, _a, _h, scope_user = _run_middleware(
            [(b"authorization", f"Bearer {raw}".encode())],
            lambda: _NoClose(db_session),
        )
        assert scope_user is not None
        assert scope_user.user_id == user.id


# ---------------------------------------------------------------------------
# Pre-auth IP throttle
# ---------------------------------------------------------------------------

class TestPreauthThrottle:
    def test_preauth_throttle_skips_db(self, monkeypatch):
        """Once the IP throttle trips, resolve()/db_factory is NOT called → 429.

        We count resolve / db_factory invocations: only the within-budget
        requests may reach the DB; every throttled (over-budget) request must be
        rejected without a query. With a budget of 3 over 5 requests, resolve is
        called at most 3 times and the over-budget requests are 429.
        """
        from limits import parse

        monkeypatch.setattr(settings, "mcp_preauth_rate_limit_enabled", True)
        monkeypatch.setattr(srv, "_preauth_rate_item", parse("3/minute"))
        reset_preauth_throttle()

        resolve_calls = {"n": 0}
        factory_calls = {"n": 0}

        def _counting_factory():
            factory_calls["n"] += 1
            return _NullDb()

        def _counting_resolve(*a, **k):
            resolve_calls["n"] += 1
            return None  # within-budget bad key → clean 401

        monkeypatch.setattr(
            MCPKeyService, "resolve", staticmethod(_counting_resolve)
        )

        codes = []
        for _ in range(5):
            code, _p, _app, hdrs, _su = _run_middleware(
                [(b"authorization", b"Bearer anything")],
                _counting_factory,
            )
            codes.append((code, hdrs))
        only_codes = [c for c, _ in codes]
        # First 3 are within budget (reach resolve → 401); the rest are throttled.
        assert only_codes[:3] == [401, 401, 401], only_codes
        assert 429 in only_codes[3:], f"throttle never tripped: {only_codes}"
        # The DB was hit AT MOST for the within-budget requests — never for a
        # throttled one (the whole point: a flood of bad keys costs no query).
        assert resolve_calls["n"] <= 3, resolve_calls
        assert factory_calls["n"] <= 3, factory_calls
        # Retry-After preserved on the pre-auth 429 path.
        for code, hdrs in codes:
            if code == 429:
                assert hdrs.get("retry-after") == "60"
                break

    def test_preauth_throttle_disabled_by_default(self, db_session, monkeypatch):
        """With the pre-auth throttle off (default), a flood is not IP-limited
        at the pre-auth layer (only the per-key layer applies)."""
        # Default is False; assert it.
        assert settings.mcp_preauth_rate_limit_enabled is False
        user = _user(db_session, uid=1)
        raw, _ = MCPKeyService.create(db_session, user.id, "k", ["read:accounts"])
        db_session.commit()
        monkeypatch.setattr(settings, "mcp_rate_limit_enabled", False)
        codes = []
        for _ in range(10):
            code, _p, _a, _h, _su = _run_middleware(
                [(b"authorization", f"Bearer {raw}".encode())],
                lambda: _NoClose(db_session),
            )
            codes.append(code)
        assert all(c == 200 for c in codes)

    def test_preauth_throttle_retry_after_header(self, monkeypatch):
        """The pre-auth 429 carries Retry-After so clients back off."""
        from limits import parse

        monkeypatch.setattr(settings, "mcp_preauth_rate_limit_enabled", True)
        monkeypatch.setattr(srv, "_preauth_rate_item", parse("1/minute"))
        reset_preauth_throttle()

        monkeypatch.setattr(
            MCPKeyService, "resolve", staticmethod(lambda *a, **k: None)
        )

        # First request consumes the budget (resolve→None→401), second is 429.
        _run_middleware([(b"authorization", b"Bearer bad")], lambda: _NullDb())
        code, _p, _a, hdrs, _su = _run_middleware(
            [(b"authorization", b"Bearer bad")], lambda: _NullDb()
        )
        assert code == 429
        assert hdrs.get("retry-after") == "60"

    def test_preauth_throttle_is_per_client(self, monkeypatch):
        """The throttle keys on the proxy-aware client — a different peer IP has
        its own budget."""
        from limits import parse

        monkeypatch.setattr(settings, "mcp_preauth_rate_limit_enabled", True)
        monkeypatch.setattr(srv, "_preauth_rate_item", parse("1/minute"))
        reset_preauth_throttle()
        monkeypatch.setattr(
            MCPKeyService, "resolve", staticmethod(lambda *a, **k: None)
        )

        f = lambda: _NullDb()
        # Exhaust client A.
        _run_middleware([(b"authorization", b"Bearer x")], f, client=("10.0.0.1", 1))
        a_blocked, *_ = _run_middleware(
            [(b"authorization", b"Bearer x")], f, client=("10.0.0.1", 2))
        # Client B still has budget.
        b_ok, *_ = _run_middleware(
            [(b"authorization", b"Bearer x")], f, client=("10.0.0.2", 1))
        assert a_blocked == 429
        assert b_ok == 401  # within budget but key invalid → reaches resolve → 401


# ---------------------------------------------------------------------------
# Audit of failures
# ---------------------------------------------------------------------------

class TestAuditFailures:
    def test_invalid_key_audited(self, db_session, caplog):
        """A bad key produces an audit record with reason 'unknown_key'."""
        with caplog.at_level("INFO", logger="mcp.audit"):
            code, _p, app_called, _h, _su = _run_middleware(
                [(b"authorization", b"Bearer totally_invalid_key")],
                lambda: _NoClose(db_session),
            )
        assert code == 401
        assert app_called is False
        reasons = [
            json.loads(r.message).get("reason")
            for r in caplog.records
            if r.name == "mcp.audit"
        ]
        assert "unknown_key" in reasons

    def test_rate_limit_hit_audited(self, db_session, caplog, monkeypatch):
        """Tripping the per-key throttle produces an audit record reason
        'rate_limited' carrying the key/user id."""
        from limits import parse

        monkeypatch.setattr(settings, "mcp_rate_limit_enabled", True)
        monkeypatch.setattr(srv, "_rate_item", parse("1/minute"))
        reset_rate_limiter()

        user = _user(db_session, uid=1)
        raw, row = MCPKeyService.create(db_session, user.id, "k", ["read:accounts"])
        db_session.commit()

        factory = lambda: _NoClose(db_session)
        with caplog.at_level("INFO", logger="mcp.audit"):
            _run_middleware([(b"authorization", f"Bearer {raw}".encode())], factory)
            code, _p, _a, _h, _su = _run_middleware(
                [(b"authorization", f"Bearer {raw}".encode())], factory)
        assert code == 429
        entries = [
            json.loads(r.message)
            for r in caplog.records
            if r.name == "mcp.audit"
        ]
        rate_entries = [e for e in entries if e.get("reason") == "rate_limited"]
        assert rate_entries, f"no rate_limited audit row: {entries}"
        assert rate_entries[0]["key_id"] == row.id
        assert rate_entries[0]["user_id"] == user.id

    def test_ip_throttle_audited(self, caplog, monkeypatch):
        """The pre-auth IP throttle audits reason 'ip_rate_limited' with the
        client key."""
        from limits import parse

        monkeypatch.setattr(settings, "mcp_preauth_rate_limit_enabled", True)
        monkeypatch.setattr(srv, "_preauth_rate_item", parse("1/minute"))
        reset_preauth_throttle()
        monkeypatch.setattr(
            MCPKeyService, "resolve", staticmethod(lambda *a, **k: None)
        )

        f = lambda: _NullDb()
        with caplog.at_level("INFO", logger="mcp.audit"):
            _run_middleware([(b"authorization", b"Bearer x")], f, client=("9.9.9.9", 1))
            _run_middleware([(b"authorization", b"Bearer x")], f, client=("9.9.9.9", 2))
        entries = [
            json.loads(r.message)
            for r in caplog.records
            if r.name == "mcp.audit"
        ]
        ip_entries = [e for e in entries if e.get("reason") == "ip_rate_limited"]
        assert ip_entries, f"no ip_rate_limited audit row: {entries}"
        assert ip_entries[0].get("client") == "9.9.9.9"
