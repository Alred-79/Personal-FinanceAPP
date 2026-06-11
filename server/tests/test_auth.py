"""Auth endpoint tests."""


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
