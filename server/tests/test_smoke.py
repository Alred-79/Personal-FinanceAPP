"""Smoke tests: verify the harness works and the FastAPI app imports/serves."""

from fastapi import FastAPI


def test_pytest_works():
    """Verify pytest framework is functional."""
    assert 1 + 1 == 2


def test_app_imports():
    """The full FastAPI app imports cleanly (env vars come from conftest)."""
    from server.src.main import app

    assert isinstance(app, FastAPI)


def test_app_responds(client):
    """The TestClient can reach the app without a server error."""
    response = client.get("/docs")
    assert response.status_code < 500
