"""Goals endpoint tests."""


def _auth_header(client, username="guser", email="g@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "G User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


_GOAL_PAYLOAD = {
    "name": "Emergency Fund",
    "description": "3 months of expenses",
    "amount": 5000.0,
    "date": "2027-01-01",
    "completed": False,
    "progress": 0.0,
}


class TestGoalsCRUD:
    def test_list_goals_empty_for_fresh_user(self, client):
        h = _auth_header(client)
        resp = client.get("/api/goals/", headers=h)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_goal_appears_in_list(self, client):
        h = _auth_header(client, "gc1", "gc1@x.com")
        resp = client.post("/api/goals/", json=_GOAL_PAYLOAD, headers=h)
        assert resp.status_code == 200, resp.text
        goals = client.get("/api/goals/", headers=h).json()
        assert len(goals) == 1
        assert goals[0]["name"] == "Emergency Fund"

    def test_create_goal_stores_amount(self, client):
        h = _auth_header(client, "gc2", "gc2@x.com")
        client.post("/api/goals/", json=_GOAL_PAYLOAD, headers=h)
        goals = client.get("/api/goals/", headers=h).json()
        assert goals[0]["amount"] == 5000.0

    def test_update_goal_name(self, client):
        h = _auth_header(client, "gu1", "gu1@x.com")
        client.post("/api/goals/", json=_GOAL_PAYLOAD, headers=h)
        gid = client.get("/api/goals/", headers=h).json()[0]["id"]
        updated = {**_GOAL_PAYLOAD, "name": "Big Fund"}
        resp = client.put(f"/api/goals/{gid}/", json=updated, headers=h)
        assert resp.status_code == 200
        goal = client.get("/api/goals/", headers=h).json()[0]
        assert goal["name"] == "Big Fund"

    def test_update_goal_progress(self, client):
        h = _auth_header(client, "gu2", "gu2@x.com")
        client.post("/api/goals/", json=_GOAL_PAYLOAD, headers=h)
        gid = client.get("/api/goals/", headers=h).json()[0]["id"]
        updated = {**_GOAL_PAYLOAD, "progress": 500.0}
        resp = client.put(f"/api/goals/{gid}/", json=updated, headers=h)
        assert resp.status_code == 200
        goal = client.get("/api/goals/", headers=h).json()[0]
        assert goal["progress"] == 500.0

    def test_delete_goal_removes_it(self, client):
        h = _auth_header(client, "gd1", "gd1@x.com")
        client.post("/api/goals/", json=_GOAL_PAYLOAD, headers=h)
        gid = client.get("/api/goals/", headers=h).json()[0]["id"]
        resp = client.delete(f"/api/goals/{gid}/", headers=h)
        assert resp.status_code == 200
        assert client.get("/api/goals/", headers=h).json() == []

    def test_delete_nonexistent_goal_returns_404(self, client):
        h = _auth_header(client, "gd2", "gd2@x.com")
        resp = client.delete("/api/goals/99999/", headers=h)
        assert resp.status_code == 404

    def test_other_user_cannot_see_goals(self, client):
        h_a = _auth_header(client, "ga", "ga@x.com")
        h_b = _auth_header(client, "gb", "gb@x.com")
        client.post("/api/goals/", json=_GOAL_PAYLOAD, headers=h_a)
        assert client.get("/api/goals/", headers=h_b).json() == []

    def test_other_user_cannot_delete_goal(self, client):
        h_a = _auth_header(client, "ga2", "ga2@x.com")
        h_b = _auth_header(client, "gb2", "gb2@x.com")
        client.post("/api/goals/", json=_GOAL_PAYLOAD, headers=h_a)
        gid = client.get("/api/goals/", headers=h_a).json()[0]["id"]
        resp = client.delete(f"/api/goals/{gid}/", headers=h_b)
        assert resp.status_code == 404
