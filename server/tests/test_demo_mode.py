"""Demo-mode security tests (docs/DEMO-MODE-PLAN.md §9).

Proves the gated demo-login is not a backdoor and the shared demo account is
protected from itself:

* ``/api/demo-login/`` 404s when the flag is off (the feature does not exist).
* ``/api/demo-status/`` reports the flag honestly so the UI can show/hide.
* When on, demo-login is PARAMETERLESS — it only ever authenticates ``demo`` and
  never touches another account; 503 when the seed hasn't been run.
* A demo session cannot change the demo password (403) or link a real bank (403),
  so one visitor can't lock out or exfiltrate through the shared account.
* The route is per-IP rate-limited like normal login.
"""

import pytest

from server.src.services.auth_service import AuthService
from server.src.settings import settings

_DEMO = {
    "username": "demo",
    "email": "demo@example.com",
    "full_name": "Demo Saver",
    "password": "Demo123!",
}


@pytest.fixture
def demo_enabled(monkeypatch):
    """Turn demo mode on for the duration of a test (restored on teardown)."""
    monkeypatch.setattr(settings, "demo_mode_enabled", True)


def _seed_demo_user(client):
    """Create the ``demo`` user through the normal signup path.

    The suite runs with ``single_user`` off, so this is the cheapest way to make
    a real, RLS-scoped demo account for the demo-login path to load.
    """
    resp = client.post(
        "/api/signup/",
        json=_DEMO,
    )
    assert resp.status_code == 200, resp.text
    # Drop the signup cookies so the next demo-login starts unauthenticated.
    client.cookies.clear()


class TestFlagGate:
    def test_demo_login_404s_when_flag_off(self, client):
        resp = client.post("/api/demo-login/")
        assert resp.status_code == 404

    def test_demo_status_false_when_off(self, client):
        resp = client.get("/api/demo-status/")
        assert resp.status_code == 200
        assert resp.json() == {"enabled": False}

    def test_demo_status_true_when_on(self, client, demo_enabled):
        resp = client.get("/api/demo-status/")
        assert resp.status_code == 200
        assert resp.json() == {"enabled": True}


class TestDemoLogin:
    def test_503_when_seed_not_run(self, client, demo_enabled):
        resp = client.post("/api/demo-login/")
        assert resp.status_code == 503

    def test_logs_in_demo_user_when_enabled_and_seeded(self, client, demo_enabled):
        _seed_demo_user(client)
        resp = client.post("/api/demo-login/")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert len(body["access_token"]) > 10
        # The session resolves to the demo user and nobody else.
        me = client.get("/api/users/me/")
        assert me.status_code == 200
        assert me.json()["username"] == "demo"

    def test_takes_no_credentials(self, client, demo_enabled):
        """Parameterless: a body is ignored, never used to authenticate."""
        _seed_demo_user(client)
        resp = client.post(
            "/api/demo-login/",
            json={"username": "someone_else", "password": "x"},
        )
        assert resp.status_code == 200, resp.text
        me = client.get("/api/users/me/")
        assert me.json()["username"] == "demo"

    def test_disabled_demo_user_403s(self, client, demo_enabled, db_session):
        _seed_demo_user(client)
        from sqlalchemy import update
        from server.src.db.models import User as UserORM

        db_session.execute(
            update(UserORM).where(UserORM.username == "demo").values(disabled=1)
        )
        db_session.commit()
        resp = client.post("/api/demo-login/")
        assert resp.status_code == 403


class TestDemoSelfImmutable:
    def test_demo_cannot_change_password(self, client, demo_enabled):
        _seed_demo_user(client)
        client.post("/api/demo-login/")
        resp = client.put(
            "/api/users/me/change-password/",
            json={"current_password": "Demo123!", "new_password": "Newpass123!"},
        )
        assert resp.status_code == 403

    def test_demo_cannot_get_plaid_link_token(self, client, demo_enabled):
        _seed_demo_user(client)
        client.post("/api/demo-login/")
        resp = client.get("/api/plaid/link-token/")
        assert resp.status_code == 403

    def test_demo_cannot_exchange_plaid_token(self, client, demo_enabled):
        _seed_demo_user(client)
        client.post("/api/demo-login/")
        resp = client.post(
            "/api/plaid/exchange-public-token/",
            json={"public_token": "public-sandbox-abc", "name": "My Bank"},
        )
        assert resp.status_code == 403

    def test_normal_user_can_still_change_password(self, client):
        """The demo guard must not affect ordinary users."""
        client.post(
            "/api/signup/",
            json={
                "username": "realuser",
                "email": "real@example.com",
                "full_name": "Real User",
                "password": "Realpass123!",
            },
        )
        resp = client.put(
            "/api/users/me/change-password/",
            json={"current_password": "Realpass123!", "new_password": "Newpass123!"},
        )
        assert resp.status_code == 200, resp.text


class TestRateLimit:
    def test_demo_login_is_rate_limited(self, client, demo_enabled, rate_limited):
        _seed_demo_user(client)
        # login_rate_limit defaults to 5/minute; the 6th tap from one IP trips it.
        codes = [client.post("/api/demo-login/").status_code for _ in range(7)]
        assert 429 in codes


class TestIsDemoHelper:
    def test_is_demo_user_matches_only_demo(self):
        from server.src.models import UserInDB

        def _u(username):
            return UserInDB(
                id=1,
                username=username,
                email="x@example.com",
                full_name="x",
                disabled=False,
                spend_warning=1,
                savings_percent=15,
                hashed_password="x",
            )

        assert AuthService and _u  # imported helpers are wired
        from server.src.services.auth_service import is_demo_user

        assert is_demo_user(_u("demo")) is True
        assert is_demo_user(_u("demo2")) is False
        assert is_demo_user(_u("alice")) is False
