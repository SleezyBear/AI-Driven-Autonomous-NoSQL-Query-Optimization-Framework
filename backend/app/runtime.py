"""Single fail-closed runtime policy for API and worker processes."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit


_DEV_DATABASE_URL = (
    "postgresql+asyncpg://control_plane:control_plane_dev_only@127.0.0.1:5432/control_plane"
)
_DEVELOPMENT_MARKERS = ("dev_only", "development", "changeme", "replace-with")
_HOST = re.compile(r"^(?:\*\.)?[A-Za-z0-9.-]+(?::[0-9]{1,5})?$")


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer.") from error
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


@dataclass(frozen=True)
class RuntimeSettings:
    environment: str
    database_url: str
    pool_size: int
    max_overflow: int
    pool_timeout_seconds: int
    pool_recycle_seconds: int
    connect_timeout_seconds: int
    statement_timeout_ms: int
    lock_timeout_ms: int
    allowed_hosts: tuple[str, ...]
    cors_allowed_origins: tuple[str, ...]
    max_request_body_bytes: int
    master_key_file: Path

    @property
    def production(self) -> bool:
        return self.environment == "production"

    @property
    def connections_per_process(self) -> int:
        return self.pool_size + self.max_overflow


def runtime_settings() -> RuntimeSettings:
    """Load and validate all environment-owned runtime settings."""
    environment = os.getenv("APP_ENV", "development").strip().lower()
    if environment not in {"development", "test", "production"}:
        raise RuntimeError("APP_ENV must be development, test, or production.")
    database_url = os.getenv(
        "DATABASE_URL", "" if environment == "production" else _DEV_DATABASE_URL
    ).strip()
    if not database_url:
        raise RuntimeError("Production requires DATABASE_URL.")
    parsed_database = urlsplit(database_url)
    if parsed_database.scheme not in {"postgresql+asyncpg", "postgresql"}:
        raise RuntimeError("DATABASE_URL must use PostgreSQL with asyncpg.")
    if environment == "production":
        password = unquote(parsed_database.password or "").lower()
        if not password or any(marker in password for marker in _DEVELOPMENT_MARKERS):
            raise RuntimeError("Production refuses development PostgreSQL credentials.")

    allowed_hosts = _csv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver,api")
    cors_origins = _csv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    if any(not _HOST.fullmatch(host) for host in allowed_hosts if host != "*"):
        raise RuntimeError("ALLOWED_HOSTS contains an invalid host.")
    if environment == "production":
        if not allowed_hosts or "*" in allowed_hosts:
            raise RuntimeError("Production requires explicit non-wildcard ALLOWED_HOSTS.")
        if not cors_origins or "*" in cors_origins:
            raise RuntimeError("Production requires explicit non-wildcard CORS_ALLOWED_ORIGINS.")

    settings = RuntimeSettings(
        environment=environment,
        database_url=database_url,
        pool_size=_integer("POSTGRES_POOL_SIZE", 5, 1, 100),
        max_overflow=_integer("POSTGRES_MAX_OVERFLOW", 5, 0, 100),
        pool_timeout_seconds=_integer("POSTGRES_POOL_TIMEOUT_SECONDS", 30, 1, 300),
        pool_recycle_seconds=_integer("POSTGRES_POOL_RECYCLE_SECONDS", 1800, 30, 86_400),
        connect_timeout_seconds=_integer("POSTGRES_CONNECT_TIMEOUT_SECONDS", 10, 1, 120),
        statement_timeout_ms=_integer("POSTGRES_STATEMENT_TIMEOUT_MS", 60_000, 100, 600_000),
        lock_timeout_ms=_integer("POSTGRES_LOCK_TIMEOUT_MS", 5_000, 100, 60_000),
        allowed_hosts=allowed_hosts,
        cors_allowed_origins=cors_origins,
        max_request_body_bytes=_integer("MAX_REQUEST_BODY_BYTES", 1_048_576, 1_024, 16_777_216),
        master_key_file=Path(
            os.getenv("CONTROL_PLANE_MASTER_KEY_FILE", "/run/secrets/control_plane_master_key")
        ),
    )
    if settings.connections_per_process > 200:
        raise RuntimeError("PostgreSQL pool budget may not exceed 200 connections per process.")
    return settings


def validate_startup_secrets(settings: RuntimeSettings) -> None:
    """Reject missing or public/example secrets before serving production traffic."""
    signing_key = os.getenv("JWT_SIGNING_KEY", "")
    if not signing_key:
        raise RuntimeError("JWT_SIGNING_KEY must be explicitly configured before startup.")
    if len(signing_key) < 32:
        raise RuntimeError("JWT_SIGNING_KEY must contain at least 32 characters.")
    if settings.production and any(marker in signing_key.lower() for marker in _DEVELOPMENT_MARKERS):
        raise RuntimeError("Production refuses an example or development JWT signing key.")
    if settings.production:
        try:
            master_key = settings.master_key_file.read_bytes()
        except OSError as error:
            raise RuntimeError("Production requires a readable control-plane master key file.") from error
        if len(master_key) != 32:
            raise RuntimeError("The production control-plane master key must contain exactly 32 bytes.")
