"""Alembic environment for the asynchronous PostgreSQL control plane."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
import time

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, async_engine_from_config


config = context.config
if database_url := os.environ.get("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None
MIGRATION_LOCK_ID = 2_026_091_901


def run_migrations_offline() -> None:
    """Run migrations without creating a database connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations using the supplied synchronous connection facade."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Apply migrations under a session advisory lock held by one runner."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    assert isinstance(connectable, AsyncEngine)

    async with connectable.connect() as connection:
        timeout = int(os.getenv("MIGRATION_LOCK_TIMEOUT_SECONDS", "120"))
        deadline = time.monotonic() + timeout
        acquired = False
        while time.monotonic() < deadline:
            acquired = bool(
                await connection.scalar(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": MIGRATION_LOCK_ID},
                )
            )
            if acquired:
                break
            await asyncio.sleep(0.25)
        if not acquired:
            raise RuntimeError("Timed out waiting for the PostgreSQL migration advisory lock.")
        # pg_try_advisory_lock is session-scoped, so committing its implicit
        # transaction keeps the lock while allowing Alembic to own/commit the
        # actual migration transaction.
        await connection.commit()
        try:
            await connection.run_sync(do_run_migrations)
        finally:
            await connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": MIGRATION_LOCK_ID},
            )

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations with an asynchronous database connection."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
