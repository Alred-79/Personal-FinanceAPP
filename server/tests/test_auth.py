"""Auth endpoint tests."""

from sqlalchemy import func, select

from server.src.db.models import User as UserORM
from server.src.services.auth_service import AuthService
from server.src.settings import settings


def _signup(client, username="authuser", email="auth@example.com", password="Test-password1"):
    return client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "Auth User",
            "password": password,
        },
    )


def _login(client, username="authuser", password="Test-password1"):
    return client.post(
        "/api/token/",
        data={"username": username, "password": password},
    )


class TestSignup:
    def test_valid_signup_returns_200_and_token(self, client):
        resp = _signup(client)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"

    def test_duplicate_username_is_rejected(self, client):
        _signup(client)
        resp = _signup(client)  # same username
        assert resp.status_code in (400, 409)

    def test_signup_access_token_is_non_empty(self, client):
        resp = _signup(client)
        assert resp.status_code == 200
        assert len(resp.json()["access_token"]) > 10


class TestLogin:
    def test_valid_credentials_return_token(self, client):
        _signup(client)
        resp = _login(client)
        assert resp.status_code == 200, resp.text
        assert "access_token" in resp.json()

    def test_wrong_password_returns_401(self, client):
        _signup(client)
        resp = _login(client, password="wrongpassword")
        assert resp.status_code == 401

    def test_nonexistent_user_returns_401(self, client):
        resp = _login(client, username="nobody_exists")
        assert resp.status_code == 401


class TestRefresh:
    def test_refresh_returns_new_access_token(self, client):
        resp1 = _signup(client)
        assert resp1.status_code == 200
        old_token = resp1.json()["access_token"]
        resp2 = client.post("/api/refresh/")
        assert resp2.status_code == 200
        new_token = resp2.json()["access_token"]
        assert new_token != old_token


class TestLogout:
    def test_logout_returns_200(self, client):
        _signup(client)
        resp = client.post("/api/logout/")
        assert resp.status_code == 200


class TestMe:
    def test_me_with_valid_token_returns_200(self, client):
        resp = _signup(client)
        token = resp.json()["access_token"]
        client.cookies.clear()
        me = client.get(
            "/api/users/me/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me.status_code == 200
        assert me.json()["username"] == "authuser"

    def test_me_without_auth_returns_401(self, client):
        client.cookies.clear()
        resp = client.get("/api/users/me/")
        assert resp.status_code == 401

    def test_me_response_has_expected_fields(self, client):
        resp = _signup(client)
        token = resp.json()["access_token"]
        client.cookies.clear()
        body = client.get(
            "/api/users/me/",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        assert "username" in body
        assert "email" in body


class TestTokenTypeIsolationOnAccessPath:
    """Assessment P2: the access path must reject a non-access ``typ`` token even
    if it's signed with the real secret and carries a ``sub`` — so an
    assistant-action or MCP-capability token can never be replayed as a session
    credential."""

    def _signed(self, payload):
        import jwt
        from datetime import datetime, timezone, timedelta

        return jwt.encode(
            {"exp": datetime.now(timezone.utc) + timedelta(hours=1), **payload},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

    def test_action_typed_token_rejected_as_access(self, client):
        _signup(client)
        client.cookies.clear()
        tok = self._signed({"sub": "authuser", "typ": "assistant_action"})
        resp = client.get("/api/users/me/", headers={"Authorization": f"Bearer {tok}"})
        assert resp.status_code == 401

    def test_capability_typed_token_rejected_as_access(self, client):
        _signup(client)
        client.cookies.clear()
        tok = self._signed({"sub": "authuser", "typ": "mcp_capability"})
        resp = client.get("/api/users/me/", headers={"Authorization": f"Bearer {tok}"})
        assert resp.status_code == 401

    def test_plain_access_token_without_typ_still_works(self, client):
        # A normal access token carries no ``typ`` and must keep working.
        resp = _signup(client)
        token = resp.json()["access_token"]
        client.cookies.clear()
        ok = client.get("/api/users/me/", headers={"Authorization": f"Bearer {token}"})
        assert ok.status_code == 200

    def test_legacy_raw_secret_token_accepted_during_grace(self, client):
        """L3 grace window: an access token minted the OLD way (raw secret, no
        ``aud``) still authenticates while ``jwt_require_aud`` is False, so logins
        issued before the deploy survive."""
        _signup(client)
        client.cookies.clear()
        legacy = self._signed({"sub": "authuser"})  # raw secret, no aud, no typ
        resp = client.get(
            "/api/users/me/", headers={"Authorization": f"Bearer {legacy}"}
        )
        assert resp.status_code == 200

    def test_legacy_raw_secret_token_rejected_when_aud_required(
        self, client, monkeypatch
    ):
        """Once the grace window closes (``jwt_require_aud=True``), a legacy
        raw-secret token is rejected — only the new aud-bearing form is valid."""
        _signup(client)
        client.cookies.clear()
        monkeypatch.setattr(settings, "jwt_require_aud", True)
        legacy = self._signed({"sub": "authuser"})
        resp = client.get(
            "/api/users/me/", headers={"Authorization": f"Bearer {legacy}"}
        )
        assert resp.status_code == 401

    def test_new_access_token_still_works_when_aud_required(self, client, monkeypatch):
        """A freshly-minted (aud-bearing) access token works with the grace window
        both open and closed."""
        monkeypatch.setattr(settings, "jwt_require_aud", True)
        token = _signup(client).json()["access_token"]
        client.cookies.clear()
        resp = client.get(
            "/api/users/me/", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200


class TestSingleUserGuard:
    """Step 01 — registration closes after the first account when single_user=True.

    The suite default is single_user=False (see conftest._suite_single_user_off),
    so each guard test here opts IN via monkeypatch. single_user is read fresh from
    the settings singleton inside the signup handler, so monkeypatch reaches it
    (this is NOT the slowapi frozen-at-construction gotcha).
    """

    def test_first_signup_succeeds(self, client, monkeypatch):
        monkeypatch.setattr(settings, "single_user", True)
        resp = _signup(client)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["access_token"]
        assert body["token_type"] == "bearer"

    def test_second_signup_blocked(self, client, db_session, monkeypatch):
        monkeypatch.setattr(settings, "single_user", True)
        first = _signup(client, username="userA", email="a@example.com")
        assert first.status_code == 200, first.text

        second = _signup(client, username="userB", email="b@example.com")
        assert second.status_code == 409, second.text
        assert "single-user" in second.json()["detail"].lower()

        # The DB still has exactly one user.
        count = db_session.execute(select(func.count(UserORM.id))).scalar_one()
        assert count == 1

    def test_second_signup_does_not_hash_password(self, client, monkeypatch):
        monkeypatch.setattr(settings, "single_user", True)
        first = _signup(client, username="userA", email="a@example.com")
        assert first.status_code == 200, first.text

        def _boom(self, password):
            raise AssertionError("password hashing must not run for a blocked signup")

        monkeypatch.setattr(AuthService, "get_password_hash", _boom)

        second = _signup(client, username="userB", email="b@example.com")
        assert second.status_code == 409, second.text

    def test_login_works_after_registration_closed(self, client, monkeypatch):
        monkeypatch.setattr(settings, "single_user", True)
        first = _signup(client, username="userA", email="a@example.com")
        assert first.status_code == 200, first.text

        # A second signup would 409 now, but the existing user can still log in.
        login = _login(client, username="userA")
        assert login.status_code == 200, login.text
        assert login.json()["access_token"]

    def test_allow_signup_false_returns_403(self, client, monkeypatch):
        # Independent of single_user: even the FIRST signup is refused.
        monkeypatch.setattr(settings, "allow_signup", False)
        resp = _signup(client)
        assert resp.status_code == 403, resp.text
        assert "disabled" in resp.json()["detail"].lower()

    def test_multi_user_signup_allowed_when_single_user_off(self, client, db_session):
        # The suite default (single_user=False) — pins that the cross-user
        # corpus is unaffected: two distinct signups both succeed.
        first = _signup(client, username="userA", email="a@example.com")
        assert first.status_code == 200, first.text
        second = _signup(client, username="userB", email="b@example.com")
        assert second.status_code == 200, second.text

        count = db_session.execute(select(func.count(UserORM.id))).scalar_one()
        assert count == 2


def _refresh_cookie_set(resp) -> bool:
    """True if *resp* sets the httpOnly refresh cookie via a Set-Cookie header."""
    return any(
        h.lower().startswith("refresh_token=")
        for h in resp.headers.get_list("set-cookie")
    )


class TestRefreshTokenNotInBody:
    """Step 07 — the refresh secret must travel ONLY in the httpOnly cookie.

    Echoing it in the JSON body would let any XSS payload read it from a fetch
    response and mint sessions, defeating the whole httpOnly design.
    """

    def test_login_body_has_no_refresh_token(self, client):
        _signup(client)
        client.cookies.clear()
        resp = _login(client)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "refresh_token" not in body
        # ...but the refresh cookie IS still set.
        assert _refresh_cookie_set(resp)

    def test_signup_body_has_no_refresh_token(self, client):
        resp = _signup(client)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "refresh_token" not in body
        assert _refresh_cookie_set(resp)

    def test_refresh_body_has_no_refresh_token(self, client):
        signup = _signup(client)
        assert signup.status_code == 200, signup.text
        resp = client.post("/api/refresh/")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "refresh_token" not in body
        # The rotated refresh cookie is still set on /refresh/.
        assert _refresh_cookie_set(resp)


def _change_password(client, current, new):
    return client.put(
        "/api/users/me/change-password/",
        json={"current_password": current, "new_password": new},
    )


class TestPasswordChangeHardening:
    """Step 07 — strength enforcement + revoke-other-sessions on password change."""

    def test_password_change_requires_correct_current(self, client):
        _signup(client)
        resp = _change_password(client, current="wrong-password", new="Brand-new1!")
        assert resp.status_code in (400, 401, 403), resp.text
        # The original password still works.
        client.cookies.clear()
        login = _login(client)
        assert login.status_code == 200, login.text

    def test_password_change_rejects_weak(self, client):
        _signup(client)
        resp = _change_password(client, current="Test-password1", new="weak")
        assert resp.status_code == 422, resp.text
        # The 422 lists the actual rules so the user can fix it in one try.
        detail = resp.json()["detail"]
        assert isinstance(detail, str)
        assert "characters" in detail.lower()
        # The old password still works — nothing changed.
        client.cookies.clear()
        login = _login(client)
        assert login.status_code == 200, login.text

    def test_password_change_succeeds_and_keeps_current_session(self, client):
        _signup(client)
        resp = _change_password(client, current="Test-password1", new="Brand-new1!")
        assert resp.status_code == 200, resp.text
        # A fresh cookie pair is issued for the current tab.
        assert _refresh_cookie_set(resp)
        # The current session can still refresh (it was NOT logged out).
        again = client.post("/api/refresh/")
        assert again.status_code == 200, again.text
        # The new password authenticates; the old one no longer does.
        client.cookies.clear()
        assert _login(client, password="Brand-new1!").status_code == 200
        assert _login(client, password="Test-password1").status_code == 401

    def test_password_change_revokes_other_sessions(self, client):
        _signup(client)
        # Log in twice -> two independent refresh tokens (two devices/tabs).
        client.cookies.clear()
        assert _login(client).status_code == 200
        session_a_refresh = client.cookies.get("refresh_token")
        assert session_a_refresh

        assert _login(client).status_code == 200
        session_b_refresh = client.cookies.get("refresh_token")
        assert session_b_refresh and session_b_refresh != session_a_refresh

        # Change the password FROM session A (re-seat its refresh cookie as the
        # current jar value — the access-token cookie still in the jar authes as
        # the same user). The change response sets a fresh cookie pair.
        client.cookies.set("refresh_token", session_a_refresh, path="/api")
        changed = _change_password(client, current="Test-password1", new="Brand-new1!")
        assert changed.status_code == 200, changed.text
        # Session A got a fresh refresh cookie; capture it from the response.
        new_a_refresh = None
        for h in changed.headers.get_list("set-cookie"):
            if h.lower().startswith("refresh_token="):
                new_a_refresh = h.split("=", 1)[1].split(";", 1)[0]
        assert new_a_refresh and new_a_refresh != session_a_refresh
        # The fresh session A cookie can still refresh (not bounced to login).
        client.cookies.clear()
        client.cookies.set("refresh_token", new_a_refresh, path="/api")
        assert client.post("/api/refresh/").status_code == 200

        # Session B's old refresh token is now revoked.
        client.cookies.clear()
        client.cookies.set("refresh_token", session_b_refresh, path="/api")
        b_refresh = client.post("/api/refresh/")
        assert b_refresh.status_code == 401, b_refresh.text


class TestUsersMeGameMode:
    """Step 07 — /users/me/ must report the real stored game_mode, not 'off'."""

    def test_users_me_reports_game_mode(self, client, db_session):
        resp = _signup(client)
        token = resp.json()["access_token"]

        # Flip the ORM game_mode directly (same engine as the client).
        row = db_session.execute(
            select(UserORM).where(UserORM.username == "authuser")
        ).scalar_one()
        row.game_mode = "full"
        db_session.commit()

        client.cookies.clear()
        me = client.get(
            "/api/users/me/", headers={"Authorization": f"Bearer {token}"}
        )
        assert me.status_code == 200, me.text
        assert me.json()["game_mode"] == "full"
