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
# NOTE (Step 02): the slowapi limiter is NOT disabled via an env var. The field
# is ``rate_limit_enabled`` (not ``limiter_enabled``, which was a no-op typo),
# and more importantly slowapi captures ``enabled`` at Limiter CONSTRUCTION and
# never re-reads the setting. So the only reliable way to keep the limiter off
# for the suite is to flip the live instance attribute — done below in
# ``_limiter_off_by_default``. Tests that assert a 429 opt back IN via the
# ``rate_limited`` fixture.
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


@pytest.fixture(autouse=True)
def _limiter_off_by_default():
    """Keep the shared slowapi limiter OFF for every test by default (Step 02).

    The old ``limiter_enabled=false`` env line was a no-op typo (the field is
    ``rate_limit_enabled``), so the limiter was accidentally ON for the whole
    suite. We can't fix it via the setting either: slowapi freezes ``enabled``
    at construction and checks the *instance* attribute per request — it never
    re-reads the setting. So flip the instance here and also clear any window
    counts a prior test left behind. Tests that need a real 429 opt back in via
    the ``rate_limited`` fixture (whose teardown runs first, LIFO, restoring the
    monkeypatch before this fixture restores the original).
    """
    from server.src.limiter import limiter

    previous = limiter.enabled
    limiter.enabled = False
    limiter.reset()
    try:
        yield
    finally:
        limiter.enabled = previous
        limiter.reset()


@pytest.fixture
def rate_limited(monkeypatch):
    """Turn the shared slowapi limiter ON for a test and reset its window.

    Flips the INSTANCE attribute (not ``settings.rate_limit_enabled``, which the
    live limiter never re-reads). ``monkeypatch`` restores it on teardown, which
    runs before the autouse ``_limiter_off_by_default`` teardown (LIFO), so the
    default-off state is correctly re-established after the test.
    """
    from server.src.limiter import limiter

    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()  # clear any prior counts so the window starts fresh
    yield limiter
    limiter.reset()


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
