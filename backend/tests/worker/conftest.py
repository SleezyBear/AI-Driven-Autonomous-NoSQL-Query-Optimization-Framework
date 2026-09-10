"""Canonical per-test PostgreSQL isolation for stateful worker integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio

from tests.support.disposable_postgres import migrated_worker_database


@pytest_asyncio.fixture
async def disposable_worker_database() -> AsyncIterator[str]:
    """Yield one fresh, fully migrated PostgreSQL database for each worker test."""
    async with migrated_worker_database() as database_url:
        yield database_url
