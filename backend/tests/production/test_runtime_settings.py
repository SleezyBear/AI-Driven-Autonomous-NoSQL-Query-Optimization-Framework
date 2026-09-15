"""Fail-closed production runtime configuration contracts."""

import pytest

from app.runtime import runtime_settings


def test_production_requires_a_non_development_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        runtime_settings()
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://control_plane:control_plane_dev_only@db/control_plane")
    with pytest.raises(RuntimeError, match="development PostgreSQL credentials"):
        runtime_settings()


def test_database_pool_policy_is_explicit_and_bounded_by_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://service:opaque@db/control_plane")
    monkeypatch.setenv("POSTGRES_POOL_SIZE", "7")
    monkeypatch.setenv("POSTGRES_MAX_OVERFLOW", "3")
    settings = runtime_settings()
    assert (settings.pool_size, settings.max_overflow, settings.statement_timeout_ms) == (7, 3, 60_000)
