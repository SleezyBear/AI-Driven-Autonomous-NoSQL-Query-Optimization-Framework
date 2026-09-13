"""Safety fixtures: security tests never point at the development database."""

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.main import app
from tests.support.disposable_postgres import migrated_worker_database


@pytest.fixture(autouse=True)
def guard_development_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Make an accidental pre-fixture database access fail closed."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://control_plane:control_plane_dev_only@127.0.0.1:5432/r19lp_security_guard",
    )
    yield


@pytest_asyncio.fixture
async def disposable_security_database() -> AsyncIterator[str]:
    async with migrated_worker_database() as database_url:
        yield database_url


@pytest.fixture
def security_client(disposable_security_database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", disposable_security_database)
    with TestClient(app) as client:
        yield client
