"""Tests for the Clerk's contextual-suggestions endpoint (P6).

Heuristic, data-aware starters for the assistant's section ticket. OFF by
default (404), enriches over the client's static fallback, never an LLM call.
"""

from server.src.settings import settings


def _auth_header(client, username="suser", email="s@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "S User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


# $5000 target, $4600 saved → $400 from done.
_NEAR_GOAL = {
    "name": "New roof",
    "description": "",
    "amount": 5000.0,
    "date": "2027-01-01",
    "completed": False,
    "progress": 4600.0,
}


class TestSuggestions:
    def test_404_when_flag_off(self, client):
        """Ship-dark default: the endpoint is invisible so the client keeps its
        static fallback."""
        h = _auth_header(client, "sg_off", "sgoff@x.com")
        resp = client.get("/api/assistant/suggestions/?context=/goals", headers=h)
        assert resp.status_code == 404

    def test_requires_auth(self, client):
        resp = client.get("/api/assistant/suggestions/?context=/goals")
        assert resp.status_code in (401, 403)

    def test_goals_suggestion_is_data_aware(self, client, monkeypatch):
        monkeypatch.setattr(settings, "assistant_suggestions_enabled", True)
        h = _auth_header(client, "sg_on", "sgon@x.com")
        client.post("/api/goals/", json=_NEAR_GOAL, headers=h)
        resp = client.get("/api/assistant/suggestions/?context=/goals", headers=h)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list) and len(data) >= 1
        # Names the user's own goal and the real remaining amount.
        assert "New roof" in data[0]["label"]
        assert "400" in data[0]["label"]
        assert data[0]["prompt"]

    def test_nested_goal_path_still_matches(self, client, monkeypatch):
        monkeypatch.setattr(settings, "assistant_suggestions_enabled", True)
        h = _auth_header(client, "sg_nest", "sgnest@x.com")
        client.post("/api/goals/", json=_NEAR_GOAL, headers=h)
        resp = client.get("/api/assistant/suggestions/?context=/goals/7", headers=h)
        assert resp.status_code == 200
        assert any("New roof" in s["label"] for s in resp.json())

    def test_no_goals_returns_empty(self, client, monkeypatch):
        monkeypatch.setattr(settings, "assistant_suggestions_enabled", True)
        h = _auth_header(client, "sg_ng", "sgng@x.com")
        resp = client.get("/api/assistant/suggestions/?context=/goals", headers=h)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_section_without_heuristic_is_empty(self, client, monkeypatch):
        """A section with no data-aware angle returns [] — the client then shows
        its static suggestion, so the layer only ever enriches."""
        monkeypatch.setattr(settings, "assistant_suggestions_enabled", True)
        h = _auth_header(client, "sg_acc", "sgacc@x.com")
        resp = client.get("/api/assistant/suggestions/?context=/accounts", headers=h)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_completed_goal_is_ignored(self, client, monkeypatch):
        monkeypatch.setattr(settings, "assistant_suggestions_enabled", True)
        h = _auth_header(client, "sg_done", "sgdone@x.com")
        client.post(
            "/api/goals/",
            json={**_NEAR_GOAL, "completed": True, "progress": 5000.0},
            headers=h,
        )
        resp = client.get("/api/assistant/suggestions/?context=/goals", headers=h)
        assert resp.status_code == 200
        assert resp.json() == []
