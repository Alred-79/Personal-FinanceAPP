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

from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from server.src.settings import settings


def _make_engine(database_url: str) -> Engine:
    connect_args = {}
    if database_url.startswith("sqlite"):
        # Required so the SQLite connection can be used across FastAPI's threads.
        connect_args["check_same_thread"] = False

    return create_engine(database_url, connect_args=connect_args, future=True)


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
