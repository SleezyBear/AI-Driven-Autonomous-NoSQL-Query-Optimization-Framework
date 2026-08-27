"""Application-owned async database runtime for production repositories."""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.db.repositories import ControlPlaneRepositories, create_repositories


LOCAL_DATABASE_URL = "postgresql+asyncpg://control_plane:control_plane_dev_only@127.0.0.1:5432/control_plane"


def create_control_plane_engine() -> AsyncEngine:
    """Create the process-local engine whose state is durably in PostgreSQL."""
    return create_async_engine(os.environ.get("DATABASE_URL", LOCAL_DATABASE_URL), pool_pre_ping=True)


def create_control_plane_repositories() -> tuple[AsyncEngine, ControlPlaneRepositories]:
    """Create the concrete production repository graph for an API or worker process."""
    engine = create_control_plane_engine()
    return engine, create_repositories(engine)
