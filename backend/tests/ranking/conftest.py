from __future__ import annotations

from collections.abc import AsyncIterator
import os

import pytest_asyncio

from tests.support.disposable_postgres import migrated_worker_database
from tests.support.ollama import unload_chat_model


@pytest_asyncio.fixture
async def disposable_diagnosis_database() -> AsyncIterator[str]:
    async with migrated_worker_database() as database_url:
        yield database_url


@pytest_asyncio.fixture(autouse=True)
async def isolated_real_ollama() -> AsyncIterator[None]:
    if os.environ.get("R19F_REAL_OLLAMA") != "1":
        yield
        return
    await unload_chat_model()
    yield
    await unload_chat_model()
