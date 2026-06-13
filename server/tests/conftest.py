import os
import pytest

# Set required environment variables for all tests
os.environ.setdefault("groq_api_key", "test_key")
os.environ.setdefault("jwt_secret_key", "test_secret")
os.environ.setdefault("jwt_algorithm", "HS256")
os.environ.setdefault("tavily_api_key", "test_key")
os.environ.setdefault("plaid_client_id", "test_id")
os.environ.setdefault("plaid_client_secret", "test_secret")
os.environ.setdefault("plaid_environment", "sandbox")
# Disable slowapi rate limiting so repeated login/refresh calls in tests
# don't trip the limiter.
os.environ.setdefault("limiter_enabled", "false")
# Disable the per-key MCP rate limit by default — its counter is process-global
# and keyed on key_id (which restarts at 1 per in-memory DB), so it would bleed
# across tests.  The dedicated 429 test enables it explicitly.
os.environ.setdefault("mcp_rate_limit_enabled", "false")

from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from server.src.db.models import Base
from server.src.settings import settings


@pytest.fixture(autouse=True)
def _suite_single_user_off():
    """Default the whole suite to multi-user-allowed (Step 01).

    The production default is ``single_user=True`` (registration closes after the
    first account). But the cross-user isolation / IDOR corpus deliberately signs
    up TWO real users in one test to prove ownership is enforced end-to-end; the
    guard would 409 the second signup. So we flip ``single_user`` off by default
    for every test. The guard's own tests opt back IN via
    ``monkeypatch.setattr(settings, "single_user", True)``.

    This is read fresh from the settings singleton inside the signup handler, so
    mutating the singleton here (and restoring it) is sufficient — unlike the
    slowapi limiter, which is frozen at construction.
    """
    previous = settings.single_user
    settings.single_user = False
    try:
        yield
    finally:
        settings.single_user = previous


@pytest.fixture
def _engine():
    """A fresh in memory SQLite engine per test, with FK enforcement on.

    StaticPool + a single shared connection keeps the in memory DB alive for the
    whole test (each new connection would otherwise get its own empty DB).
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def db_session(_engine):
    """A SQLAlchemy session bound to the per test in memory engine."""
    TestingSessionLocal = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, future=True
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(_engine):
    """TestClient with get_db overridden to use the per test in memory engine."""
    from fastapi.testclient import TestClient
    from server.src.main import app
    from server.src.db.session import get_db

    TestingSessionLocal = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, future=True
    )

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
