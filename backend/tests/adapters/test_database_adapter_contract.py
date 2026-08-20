"""Contract tests shared by the fake and MongoDB typed adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.adapters.contracts import DatabaseAdapter, IndexSpec, Namespace
from app.adapters.fake import FakeDatabaseAdapter
from app.adapters.mongodb import MongoDBAdapter


class InMemoryIndexCursor:
    """Minimal async cursor implementing MongoDB's list-index iteration shape."""

    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = documents

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[dict[str, Any]]:
        for document in self._documents:
            yield document


class InMemoryMongoCollection:
    """Test double implementing only the Mongo adapter's typed collection methods."""

    def __init__(self) -> None:
        self.indexes: dict[str, tuple[tuple[str, int], ...]] = {}

    def list_indexes(self) -> InMemoryIndexCursor:
        return InMemoryIndexCursor(
            [
                {"name": name, "key": dict(keys)}
                for name, keys in sorted(self.indexes.items())
            ]
        )

    async def create_index(self, keys: list[tuple[str, int]], name: str) -> str:
        self.indexes[name] = tuple(keys)
        return name

    async def drop_index(self, name: str) -> None:
        self.indexes.pop(name, None)


class InMemoryMongoDatabase:
    """Test-double database with deterministic typed collection access."""

    def __init__(self) -> None:
        self.collections: dict[str, InMemoryMongoCollection] = {"orders": InMemoryMongoCollection()}

    async def list_collection_names(self) -> list[str]:
        return list(self.collections)

    def get_collection(self, name: str) -> InMemoryMongoCollection:
        return self.collections.setdefault(name, InMemoryMongoCollection())


class InMemoryMongoClient:
    """Test-double client with one named database."""

    def __init__(self) -> None:
        self.database = InMemoryMongoDatabase()

    def get_database(self, name: str) -> InMemoryMongoDatabase:
        assert name == "commerce"
        return self.database


@pytest.fixture(params=["fake", "mongo"])
def adapter(request: pytest.FixtureRequest) -> DatabaseAdapter:
    namespace = Namespace(collection="orders")
    if request.param == "fake":
        return FakeDatabaseAdapter((namespace,))
    return MongoDBAdapter(InMemoryMongoClient(), "commerce")


@pytest.mark.asyncio
async def test_adapter_contract_for_typed_index_operations(adapter: DatabaseAdapter) -> None:
    namespace = Namespace(collection="orders")
    index = IndexSpec(name="customer_created", keys=(("customer_id", 1), ("created_at", -1)))

    assert await adapter.list_namespaces() == (namespace,)
    assert await adapter.list_indexes(namespace) == ()

    await adapter.create_index(namespace, index)
    assert await adapter.list_indexes(namespace) == (index,)

    await adapter.drop_index(namespace, index.name)
    assert await adapter.list_indexes(namespace) == ()


def test_database_adapter_has_no_arbitrary_command_method() -> None:
    assert not hasattr(DatabaseAdapter, "execute_arbitrary_command")

