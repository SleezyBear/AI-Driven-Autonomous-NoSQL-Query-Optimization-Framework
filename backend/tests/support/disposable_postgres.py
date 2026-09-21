"""Safe, fully migrated disposable PostgreSQL databases for integration tests."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


_PREFIX = "nosql_test_worker_"
_SAFE_NAME = re.compile(r"^nosql_test_worker_[a-z0-9_]+$")
_SERVER_URL = os.environ.get(
    "TEST_POSTGRES_SERVER_URL",
    "postgresql+asyncpg://control_plane:control_plane_dev_only@127.0.0.1:5432/postgres",
)
_ROOT = Path(__file__).resolve().parents[3]


@asynccontextmanager
async def migrated_worker_database() -> object:
    """Yield a unique Alembic-migrated test DB and safely drop it afterwards."""
    name = _PREFIX + uuid4().hex
    if not _SAFE_NAME.fullmatch(name):
        raise RuntimeError("unsafe disposable database name")
    server = create_async_engine(_SERVER_URL, isolation_level="AUTOCOMMIT")
    database_url = _SERVER_URL.rsplit("/", 1)[0] + "/" + name
    try:
        async with server.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
        env = {**os.environ, "DATABASE_URL": database_url}
        subprocess.run([sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"], cwd=_ROOT, env=env, check=True)
        yield database_url
    finally:
        if not _SAFE_NAME.fullmatch(name):
            raise RuntimeError("refusing to drop a non-test database")
        async with server.connect() as connection:
            await connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid <> pg_backend_pid()"), {"name": name})
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        await server.dispose()
