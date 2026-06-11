"""Tests for the MCP key management REST API.

Coverage:
* POST /api/mcp-keys/ — create returns raw key once; invalid scopes → 400.
* GET /api/mcp-keys/  — list returns prefixes only (no hashes / raw keys).
* DELETE /api/mcp-keys/{id}/ — revoke works; subsequent requests rejected.
* User isolation — user A cannot list or delete user B's keys.
* Rate limiting — excessive creates → 429.
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signup_and_auth(client, username="alice", email="alice@example.com"):
    """Sign up a user and return their Bearer auth header."""
    r = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": username.title(),
            "password": "Test-password1!",
        },
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _create_key(client, headers, name="mykey", scopes=None):
    """Helper: POST /api/mcp-keys/ and return the full response."""
    return client.post(
        "/api/mcp-keys/",
        json={"name": name, "scopes": ["read:accounts"] if scopes is None else scopes},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Create key
# ---------------------------------------------------------------------------

class TestCreateKey:
    def test_returns_raw_key_once(self, client):
        headers = _signup_and_auth(client)
        r = _create_key(client, headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "raw_key" in body
        assert body["raw_key"].startswith("bdgt_live_")

    def test_response_includes_metadata(self, client):
        headers = _signup_and_auth(client)
        r = _create_key(client, headers, name="my-key", scopes=["read:accounts"])
        body = r.json()
        assert body["name"] == "my-key"
        assert "read:accounts" in body["scopes"]
        assert "key_prefix" in body
        assert "expires_at" in body

    def test_raw_key_not_in_list_after_creation(self, client):
        """The raw key must never appear in the list endpoint."""
        headers = _signup_and_auth(client)
        r = _create_key(client, headers)
        raw = r.json()["raw_key"]

        listed = client.get("/api/mcp-keys/", headers=headers).json()
        listed_str = str(listed)
        assert raw not in listed_str

    def test_invalid_scope_returns_400(self, client):
        headers = _signup_and_auth(client)
        r = _create_key(client, headers, scopes=["nuclear:launch"])
        assert r.status_code == 400

    def test_empty_scopes_returns_400(self, client):
        headers = _signup_and_auth(client)
        r = _create_key(client, headers, scopes=[])
        assert r.status_code == 400

    def test_unauthenticated_returns_401(self, client):
        r = _create_key(client, {})
        assert r.status_code == 401

    def test_valid_mcp_scope_accepted(self, client):
        headers = _signup_and_auth(client)
        r = _create_key(client, headers, scopes=["read:transactions", "read:budgets"])
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# List keys
# ---------------------------------------------------------------------------

class TestListKeys:
    def test_list_returns_empty_for_new_user(self, client):
        headers = _signup_and_auth(client)
        r = client.get("/api/mcp-keys/", headers=headers)
        assert r.status_code == 200
        assert r.json() == []

    def test_list_shows_created_key(self, client):
        headers = _signup_and_auth(client)
        _create_key(client, headers, name="k1")
        r = client.get("/api/mcp-keys/", headers=headers)
        keys = r.json()
        assert len(keys) == 1
        assert keys[0]["name"] == "k1"

    def test_list_shows_prefix_not_hash(self, client):
        headers = _signup_and_auth(client)
        _create_key(client, headers)
        keys = client.get("/api/mcp-keys/", headers=headers).json()
        key = keys[0]
        assert "key_prefix" in key
        assert "key_hash" not in key
        assert "raw_key" not in key

    def test_list_shows_multiple_keys(self, client):
        headers = _signup_and_auth(client)
        _create_key(client, headers, name="k1")
        _create_key(client, headers, name="k2")
        keys = client.get("/api/mcp-keys/", headers=headers).json()
        assert len(keys) == 2
        names = {k["name"] for k in keys}
        assert names == {"k1", "k2"}

    def test_unauthenticated_list_returns_401(self, client):
        r = client.get("/api/mcp-keys/")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Revoke key
# ---------------------------------------------------------------------------

class TestRevokeKey:
    def test_revoke_marks_key_revoked(self, client):
        headers = _signup_and_auth(client)
        r = _create_key(client, headers, name="to-revoke")
        key_id = r.json()["id"]

        r2 = client.delete(f"/api/mcp-keys/{key_id}/", headers=headers)
        assert r2.status_code == 200
        assert r2.json()["revoked"] is True

    def test_revoked_key_appears_as_revoked_in_list(self, client):
        headers = _signup_and_auth(client)
        r = _create_key(client, headers, name="r-key")
        key_id = r.json()["id"]
        client.delete(f"/api/mcp-keys/{key_id}/", headers=headers)

        keys = client.get("/api/mcp-keys/", headers=headers).json()
        k = next(k for k in keys if k["id"] == key_id)
        assert k["revoked"] is True

    def test_revoke_nonexistent_key_returns_404(self, client):
        headers = _signup_and_auth(client)
        r = client.delete("/api/mcp-keys/99999/", headers=headers)
        assert r.status_code == 404

    def test_double_revoke_is_idempotent(self, client):
        headers = _signup_and_auth(client)
        r = _create_key(client, headers, name="idem")
        key_id = r.json()["id"]
        client.delete(f"/api/mcp-keys/{key_id}/", headers=headers)
        r2 = client.delete(f"/api/mcp-keys/{key_id}/", headers=headers)
        assert r2.status_code == 200  # second revoke still 200 (idempotent)


# ---------------------------------------------------------------------------
# User isolation
# ---------------------------------------------------------------------------

class TestUserIsolation:
    def test_user_a_cannot_see_user_b_keys(self, client):
        headers_a = _signup_and_auth(client, "userA", "a@example.com")
        headers_b = _signup_and_auth(client, "userB", "b@example.com")

        _create_key(client, headers_a, name="a-key")

        keys_b = client.get("/api/mcp-keys/", headers=headers_b).json()
        names_b = [k["name"] for k in keys_b]
        assert "a-key" not in names_b

    def test_user_a_cannot_revoke_user_b_key(self, client):
        headers_a = _signup_and_auth(client, "userC", "c@example.com")
        headers_b = _signup_and_auth(client, "userD", "d@example.com")

        r = _create_key(client, headers_b, name="b-key")
        key_id = r.json()["id"]

        # User A tries to revoke user B's key
        r2 = client.delete(f"/api/mcp-keys/{key_id}/", headers=headers_a)
        assert r2.status_code == 404


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimit:
    def test_excessive_creates_return_429(self, client, monkeypatch):
        """Hitting the key creation endpoint more than the rate limit → 429."""
        from server.src.settings import settings
        # Temporarily tighten the limit so the test is fast
        monkeypatch.setattr(settings, "mcp_key_rate_limit", "3/minute")
        # Re-enable rate limiting for this test
        monkeypatch.setattr(settings, "rate_limit_enabled", True)

        headers = _signup_and_auth(client, "ratelimituser", "rl@example.com")

        responses = []
        for i in range(10):
            r = _create_key(client, headers, name=f"key-{i}")
            responses.append(r.status_code)

        assert 429 in responses, (
            f"Expected at least one 429 (rate-limited), got: {responses}"
        )
