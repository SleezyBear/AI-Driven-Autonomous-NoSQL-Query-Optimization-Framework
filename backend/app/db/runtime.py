"""Application-owned async database runtime for production repositories."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.db.repositories import ControlPlaneRepositories, create_repositories
from app.runtime import runtime_settings


def create_control_plane_engine() -> AsyncEngine:
    """Create the process-local engine whose state is durably in PostgreSQL."""
    settings = runtime_settings()
    return create_async_engine(
        settings.database_url, pool_pre_ping=True, pool_size=settings.pool_size,
        max_overflow=settings.max_overflow, pool_timeout=settings.pool_timeout_seconds,
        pool_recycle=settings.pool_recycle_seconds,
        connect_args={
            "timeout": settings.connect_timeout_seconds,
            "server_settings": {
                "statement_timeout": str(settings.statement_timeout_ms),
                "lock_timeout": str(settings.lock_timeout_ms),
                "application_name": "nosql_optimizer_control_plane",
            },
        },
    )


def create_control_plane_repositories() -> tuple[AsyncEngine, ControlPlaneRepositories]:
    """Create the concrete production repository graph for an API or worker process."""
    engine = create_control_plane_engine()
    return engine, create_repositories(engine)
