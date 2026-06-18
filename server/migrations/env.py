import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Import the ORM metadata. ``prepend_sys_path = .`` in alembic.ini puts the repo
# root on sys.path so this import resolves. We intentionally do NOT import the
# full application ``Settings`` here: that object requires every app env var
# (groq/jwt/plaid/...) to be present, which would make running migrations need a
# full app environment. The DB URL is the only setting migrations care about, so
# we resolve it directly from the ``database_url`` env var with a default that
# matches ``settings.database_url``.
from server.src.db.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Override the placeholder URL from alembic.ini with the real one. This is what
# lets ``database_url=sqlite:////tmp/bai_fresh.db alembic upgrade head`` work.
# WS2: prefer ALEMBIC_DATABASE_URL when set. Under RLS the app connects as a
# restricted, non-superuser role (pf_app) that CANNOT create policies / ALTER
# tables; migrations must run as a BYPASSRLS owner role. Point ALEMBIC_DATABASE_URL
# at that role so `alembic upgrade head` works while the app keeps DATABASE_URL.
config.set_main_option(
    "sqlalchemy.url",
    os.environ.get("ALEMBIC_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or os.environ.get("database_url", "sqlite:///finance_tracker.db"),
)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Batch mode is a SQLite-only workaround (it can't ALTER in place). On
        # Postgres it is unnecessary and can mangle ALTERs, so enable it only for
        # SQLite, detected here from the URL since offline mode has no connection.
        render_as_batch=(url or "").startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite-only batch mode (see offline note above): keyed off the live
            # connection's dialect so a Postgres run gets native ALTERs.
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
