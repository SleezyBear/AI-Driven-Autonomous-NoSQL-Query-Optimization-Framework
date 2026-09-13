from collections.abc import AsyncIterator

import pytest_asyncio

from tests.support.disposable_postgres import migrated_worker_database


@pytest_asyncio.fixture
async def disposable_workload_database() -> AsyncIterator[str]:
    async with migrated_worker_database() as database_url:
        yield database_url
