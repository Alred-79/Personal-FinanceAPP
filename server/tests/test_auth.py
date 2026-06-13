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
