"""Alembic environment for Clarivo.

Reuses the application's own connection logic (`backend.services.db`) rather than
re-deriving a URL, so migrations connect exactly the way the app does — including
the Supabase pooler settings (prepared statements disabled) and the pinned CA for
verified TLS. Getting that wrong is a classic source of "works in the app, fails in
the migration".
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import the app's metadata and connection helpers.
from backend.models import Base
from backend.services.db import _build_url, _connect_args  # noqa: PLC2701

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    url = _build_url()
    if url is None:
        raise RuntimeError(
            "Database is not configured. Set DATABASE_URL (or the DB_HOST/DB_USER/"
            "DB_PASSWORD parts) in .env before running migrations."
        )
    # render_as_string(hide_password=False) keeps special characters intact.
    return url.render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it.

    Useful for review before touching a production database:
        alembic upgrade head --sql
    """
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Catch column type and default drift, not just added/removed columns.
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url = _build_url()
    connectable = async_engine_from_config(
        {"sqlalchemy.url": _url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        # Same connect args as the app: pgbouncer-safe and TLS-verified.
        connect_args=_connect_args(url.host),
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
