"""Engine and session setup for the request scoped SQLAlchemy session.

The engine is built from ``settings.database_url`` (default
``sqlite:///finance_tracker.db``). For SQLite we:

* pass ``check_same_thread=False`` so the connection can be shared across the
  threads FastAPI uses, and
* register a ``connect`` event hook that turns on WAL journaling and enforces
  foreign keys (SQLite leaves FK enforcement off by default, one connection at a time).

``get_db`` is the FastAPI dependency: it yields a session, commits on success,
rolls back on any exception, and always closes.
"""

import os
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from server.src.settings import settings


def _make_engine(database_url: str) -> Engine:
    connect_args = {}
    engine_kwargs = {}
    if database_url.startswith("sqlite"):
        # Required so the SQLite connection can be used across FastAPI's threads.
        connect_args["check_same_thread"] = False
    elif os.environ.get("PYTEST_PG_SHARED_CONN") == "1":
        # TEST-ONLY (set by server/tests/conftest.py when TEST_DATABASE_URL points
        # at Postgres): one shared connection, like the SQLite ``StaticPool`` the
        # suite is written against. The request path, app-internal
        # ``SessionLocal()`` (e.g. the assistant's reconcile session), and a
        # test's own ``db_session`` then all see ONE connection/transaction — so
        # the suite's single-connection assumptions hold and we don't hit
        # cross-connection lock waits that the single-process SQLite never had.
        # NEVER set in production: a real pool is required there for concurrency.
        engine_kwargs["poolclass"] = StaticPool
    else:
        # Server engines (Postgres) use a real connection pool. ``pool_pre_ping``
        # transparently recycles a connection the server dropped (idle timeout,
        # failover) instead of surfacing a stale-connection error on the request.
        engine_kwargs["pool_pre_ping"] = True

    return create_engine(
        database_url, connect_args=connect_args, future=True, **engine_kwargs
    )


engine = _make_engine(settings.database_url)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Turn on WAL and foreign key enforcement for each new SQLite connection."""
    # Only meaningful for SQLite; guard so a future Postgres URL is unaffected.
    if engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        # Single-writer model: a concurrent writer (e.g. a background sync while
        # a request commits game events) should wait briefly for the lock rather
        # than fail immediately with "database is locked".
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, future=True
)


@event.listens_for(SessionLocal, "after_begin")
def _bind_tenant_from_context(session, transaction, connection):
    """WS2 safety-net: bind the RLS tenant for app-internal ``SessionLocal()``
    own-sessions (the assistant's tool/reconcile sessions, etc.) that don't flow
    through ``get_tenant_db``. Reads the per-request ``user_id`` contextvar that
    auth already populates, so any own-session opened within a request's context
    inherits the tenant. No-op unless enable_rls + Postgres, and when no user is
    bound (background/admin jobs — those use a BYPASSRLS role; see scheduler_database_url).
    The request path itself is bound explicitly by get_tenant_db (correct post-auth
    timing); this fires harmlessly there too."""
    if not settings.enable_rls or connection.dialect.name != "postgresql":
        return
    from server.src.logging_context import user_id_var

    from .rls import set_tenant

    uid = user_id_var.get()
    if uid and uid != "-" and str(uid).isdigit():
        set_tenant(session, int(uid))


def get_db() -> Iterator[Session]:
    """Yield a request scoped session: commit on success, roll back on error."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
