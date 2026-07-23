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
from server.src.services.demo_readiness import DemoReadiness
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


@pytest.fixture
def demo_ready(monkeypatch):
    """Isolate auth/security tests from the separately tested seed contract."""
    import server.src.routers.auth as auth_router

    monkeypatch.setattr(
        auth_router,
        "assess_demo_readiness",
        lambda *_args, **_kwargs: DemoReadiness(True, "ready", "ready"),
    )


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
        assert resp.json() == {
            "enabled": False,
            "ready": False,
            "state": "disabled",
            "reason_code": "demo_disabled",
        }

    def test_demo_status_enabled_but_unready_on_unmigrated_schema(self, client, demo_enabled):
        resp = client.get("/api/demo-status/")
        assert resp.status_code == 200
        assert resp.json() == {
            "enabled": True,
            "ready": False,
            "state": "unavailable",
            "reason_code": "schema_outdated",
        }

    def test_readiness_binds_demo_tenant_before_rls_seed_reads(
        self, db_session, demo_enabled, monkeypatch
    ):
        import server.src.services.demo_readiness as readiness
        from server.src.db.models import Goal, User

        user = User(
            username="demo",
            email="demo@example.com",
            full_name="Maya Chen",
            hashed_password="x",
            game_mode="off",
        )
        db_session.add(user)
        db_session.flush()
        db_session.add(Goal(
            user_id=user.id,
            name="Tax Reserve",
            description="",
            amount=100_00,
            progress=0,
            date="2027-01-01",
            completed=0,
        ))
        db_session.flush()

        bound: list[int] = []
        monkeypatch.setattr(readiness, "_schema_is_current", lambda _db: True)
        monkeypatch.setattr(readiness, "_MINIMUM_COUNTS", {})
        monkeypatch.setattr(settings, "enable_rls", True)
        monkeypatch.setattr(readiness, "set_tenant", lambda _db, uid: bound.append(uid))
        monkeypatch.setattr(
            readiness,
            "_rules_are_engine_valid",
            lambda _db, uid: bound == [uid],
        )
        monkeypatch.setattr(
            readiness,
            "_canonical_seed_is_intact",
            lambda _db, uid: bound == [uid],
        )

        result = readiness.assess_demo_readiness(db_session, enabled=True)
        assert result.ready is True
        assert bound == [user.id]


class TestDemoLogin:
    def test_503_when_seed_not_run(self, client, demo_enabled):
        resp = client.post("/api/demo-login/")
        assert resp.status_code == 503
        assert "set-cookie" not in resp.headers
        assert resp.json()["detail"]["reason_code"] == "schema_outdated"

    def test_logs_in_demo_user_when_enabled_and_seeded(self, client, demo_enabled, demo_ready):
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
        assert me.json()["is_demo"] is True

    def test_takes_no_credentials(self, client, demo_enabled, demo_ready):
        """Parameterless: a body is ignored, never used to authenticate."""
        _seed_demo_user(client)
        resp = client.post(
            "/api/demo-login/",
            json={"username": "someone_else", "password": "x"},
        )
        assert resp.status_code == 200, resp.text
        me = client.get("/api/users/me/")
        assert me.json()["username"] == "demo"

    def test_disabled_demo_user_403s(self, client, demo_enabled, demo_ready, db_session):
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
    def test_demo_cannot_change_password(self, client, demo_enabled, demo_ready):
        _seed_demo_user(client)
        client.post("/api/demo-login/")
        resp = client.put(
            "/api/users/me/change-password/",
            json={"current_password": "Demo123!", "new_password": "Newpass123!"},
        )
        assert resp.status_code == 403

    def test_demo_cannot_get_plaid_link_token(self, client, demo_enabled, demo_ready):
        _seed_demo_user(client)
        client.post("/api/demo-login/")
        resp = client.get("/api/plaid/link-token/")
        assert resp.status_code == 403

    def test_demo_cannot_exchange_plaid_token(self, client, demo_enabled, demo_ready):
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


class TestSharedDemoReadOnly:
    _DETAIL = {
        "detail": {
            "code": "demo_read_only",
            "message": (
                "Sample data is read-only. Decision and rule previews still work; "
                "create your own ledger to add, edit, or delete records."
            ),
        }
    }

    @staticmethod
    def _login(client, demo_enabled, demo_ready):
        _seed_demo_user(client)
        response = client.post("/api/demo-login/")
        assert response.status_code == 200, response.text

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("post", "/api/budgets/", {"category": "Food", "monthly_limit": 500}),
            ("put", "/api/budgets/1/", {"category": "Food", "monthly_limit": 450}),
            ("delete", "/api/budgets/1/", None),
            ("post", "/api/goals/", {"name": "Trip", "amount": 2000, "date": "2027-06-01"}),
            ("put", "/api/goals/1/", {"name": "Trip", "amount": 2500, "date": "2027-06-01"}),
            ("delete", "/api/goals/1/", None),
            ("post", "/api/rules/", {"name": "Alert", "action_type": "notify"}),
            ("put", "/api/rules/1/", {"name": "Alert", "action_type": "notify"}),
            ("patch", "/api/rules/1/", {"enabled": False}),
            ("delete", "/api/rules/1/", None),
            ("post", "/api/accounts/", {"name": "Checking", "type": "checking", "balance": 1000}),
            ("put", "/api/accounts/1/", {"name": "Checking", "type": "checking", "balance": 900}),
            ("delete", "/api/accounts/1/", None),
            ("post", "/api/expenses/", {"account_id": 1, "title": "Groceries", "amount": 50, "date": "2026-07-23", "category": "Food"}),
            ("put", "/api/expenses/1/", {"account_id": 1, "title": "Groceries", "amount": 45, "date": "2026-07-23", "category": "Food"}),
            ("delete", "/api/expenses/1/", None),
            ("post", "/api/scenarios/", {"name": "New plan", "overlay": {}}),
            ("put", "/api/scenarios/1/", {"name": "New plan", "overlay": {}}),
            ("delete", "/api/scenarios/1/", None),
        ],
    )
    def test_financial_crud_is_blocked_before_route_code(
        self, client, demo_enabled, demo_ready, method, path, body
    ):
        self._login(client, demo_enabled, demo_ready)
        before = client.get("/api/demo-status/")
        assert before.json()["ready"] is True

        response = client.request(method, path, json=body)

        assert response.status_code == 403, response.text
        assert response.json() == self._DETAIL
        # A refused command cannot damage the canonical readiness contract.
        after = client.get("/api/demo-status/")
        assert after.json() == before.json()

    def test_read_only_preview_posts_remain_available(
        self, client, db_session, demo_enabled, demo_ready, monkeypatch
    ):
        self._login(client, demo_enabled, demo_ready)
        monkeypatch.setattr(settings, "plan_composer_enabled", True)

        rule = client.post(
            "/api/rules/preview/",
            json={
                "conditions": [{"field": "amount", "op": "gt", "value": 25}],
                "action_type": "notify",
                "action_params": {"message": "Large purchase"},
                "sample_txns": [{"id": 1, "type": "expense", "amount": 40}],
            },
        )
        assert rule.status_code == 200, rule.text

        from sqlalchemy import select
        from server.src.db.models import Scenario, User

        user = db_session.execute(
            select(User).where(User.username == "demo")
        ).scalar_one()
        saved = Scenario(user_id=user.id, name="Saved preview", overlay_json="{}")
        db_session.add(saved)
        db_session.commit()

        compose = client.post(
            "/api/scenarios/compose-preview/",
            json={
                "max_allocation": 0,
                "additional_buffer_floor": 0,
                "goal_ids": [],
                "horizon_days": 30,
            },
        )
        ad_hoc = client.post(
            "/api/scenarios/evaluate/",
            json={"name": "Ad hoc preview", "horizon_days": 30, "overlay": {}},
        )
        compare = client.post(
            "/api/scenarios/compare/",
            json={"scenario_ids": [saved.id], "horizon_days": 30},
        )
        saved_evaluate = client.post(
            f"/api/scenarios/{saved.id}/evaluate/?horizon_days=30"
        )
        for response in (compose, ad_hoc, compare, saved_evaluate):
            assert response.status_code == 200, response.text

    def test_normal_user_writes_still_work_when_demo_mode_is_on(
        self, client, demo_enabled
    ):
        client.post(
            "/api/signup/",
            json={
                "username": "normal-writer",
                "email": "normal-writer@example.com",
                "full_name": "Normal Writer",
                "password": "Normal123!",
            },
        )
        response = client.post(
            "/api/accounts/",
            json={"name": "My Checking", "type": "checking", "balance": 1000},
        )
        assert response.status_code == 200, response.text

    def test_demo_named_user_writes_still_work_when_demo_mode_is_off(self, client):
        response = client.post("/api/signup/", json=_DEMO)
        assert response.status_code == 200, response.text
        write = client.post(
            "/api/accounts/",
            json={"name": "Checking", "type": "checking", "balance": 1000},
        )
        assert write.status_code == 200, write.text


class TestRateLimit:
    def test_demo_login_is_rate_limited(self, client, demo_enabled, demo_ready, rate_limited):
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


class TestSharedDemoRefreshIsolation:
    def test_reused_demo_token_does_not_revoke_other_visitors(
        self, client, db_session, demo_enabled
    ):
        _seed_demo_user(client)
        from fastapi import HTTPException
        from sqlalchemy import func, select
        from server.src.db.models import RefreshToken, User

        user = db_session.execute(
            select(User).where(User.username == "demo")
        ).scalar_one()
        stale = AuthService.create_refresh_token(db_session, user.id)
        AuthService.create_refresh_token(db_session, user.id)  # another visitor
        AuthService.rotate_refresh_token(db_session, stale)  # current visitor rotates
        db_session.commit()
        active_before_reuse = db_session.execute(
            select(func.count(RefreshToken.id)).where(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked == 0,
            )
        ).scalar_one()

        with pytest.raises(HTTPException) as exc:
            AuthService.rotate_refresh_token(db_session, stale)
        assert exc.value.status_code == 401
        active = db_session.execute(
            select(func.count(RefreshToken.id)).where(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked == 0,
            )
        ).scalar_one()
        assert active == active_before_reuse

    def test_reused_normal_token_still_revokes_whole_family(
        self, client, db_session
    ):
        from fastapi import HTTPException
        from sqlalchemy import func, select
        from server.src.db.models import RefreshToken, User

        client.post("/api/signup/", json={
            "username": "family-user",
            "email": "family@example.com",
            "full_name": "Family User",
            "password": "Family123!",
        })
        user = db_session.execute(
            select(User).where(User.username == "family-user")
        ).scalar_one()
        stale = AuthService.create_refresh_token(db_session, user.id)
        AuthService.create_refresh_token(db_session, user.id)
        AuthService.rotate_refresh_token(db_session, stale)
        db_session.commit()

        with pytest.raises(HTTPException):
            AuthService.rotate_refresh_token(db_session, stale)
        active = db_session.execute(
            select(func.count(RefreshToken.id)).where(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked == 0,
            )
        ).scalar_one()
        assert active == 0
