"""Single fail-closed runtime policy for API and worker processes."""

from __future__ import annotations

import os
from dataclasses import dataclass


_DEV_DATABASE_URL = "postgresql+asyncpg://control_plane:control_plane_dev_only@127.0.0.1:5432/control_plane"


@dataclass(frozen=True)
class RuntimeSettings:
    environment: str
    database_url: str
    pool_size: int
    max_overflow: int
    pool_timeout_seconds: int
    pool_recycle_seconds: int
    statement_timeout_ms: int
    lock_timeout_ms: int

    @property
    def production(self) -> bool:
        return self.environment == "production"


def runtime_settings() -> RuntimeSettings:
    environment = os.getenv("APP_ENV", "development")
    if environment not in {"development", "test", "production"}:
        raise RuntimeError("APP_ENV must be development, test, or production.")
    database_url = os.getenv("DATABASE_URL", "" if environment == "production" else _DEV_DATABASE_URL)
    if not database_url:
        raise RuntimeError("Production requires DATABASE_URL.")
    if environment == "production" and "control_plane_dev_only" in database_url:
        raise RuntimeError("Production refuses development PostgreSQL credentials.")
    return RuntimeSettings(
        environment, database_url, int(os.getenv("POSTGRES_POOL_SIZE", "5")),
        int(os.getenv("POSTGRES_MAX_OVERFLOW", "5")), int(os.getenv("POSTGRES_POOL_TIMEOUT_SECONDS", "30")),
        int(os.getenv("POSTGRES_POOL_RECYCLE_SECONDS", "1800")), int(os.getenv("POSTGRES_STATEMENT_TIMEOUT_MS", "60000")),
        int(os.getenv("POSTGRES_LOCK_TIMEOUT_MS", "5000")),
    )
