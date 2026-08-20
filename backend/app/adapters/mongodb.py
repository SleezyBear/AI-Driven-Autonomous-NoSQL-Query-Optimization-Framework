"""MongoDB implementation of the typed DatabaseAdapter contract."""

from __future__ import annotations

from typing import Any, Protocol, cast

from app.adapters.contracts import DatabaseAdapter, IndexSpec, Namespace


class MongoCollectionProtocol(Protocol):
    """The restricted asynchronous PyMongo collection operations used here."""

    def list_indexes(self) -> Any:
        """Return the asynchronous index cursor."""

    async def create_index(self, keys: list[tuple[str, int]], name: str) -> str:
        """Create an index and return its name."""

    async def drop_index(self, name: str) -> None:
        """Drop an index by its typed name."""


class MongoDatabaseProtocol(Protocol):
    """The restricted asynchronous PyMongo database operations used here."""

    async def list_collection_names(self) -> list[str]:
        """List collection names."""

    def get_collection(self, name: str) -> MongoCollectionProtocol:
        """Return a collection by name."""


class MongoClientProtocol(Protocol):
    """The restricted client operation used to select the configured database."""

    def get_database(self, name: str) -> MongoDatabaseProtocol:
        """Return the configured database."""


class MongoDBAdapter(DatabaseAdapter):
    """Use an injected async Mongo client through typed metadata/index operations only."""

    def __init__(self, client: MongoClientProtocol, database_name: str) -> None:
        self._database = client.get_database(database_name)

    async def list_namespaces(self) -> tuple[Namespace, ...]:
        names = await self._database.list_collection_names()
        return tuple(Namespace(collection=name) for name in sorted(names))

    async def list_indexes(self, namespace: Namespace) -> tuple[IndexSpec, ...]:
        cursor = self._database.get_collection(namespace.collection).list_indexes()
        documents = [document async for document in cursor]
        return tuple(
            IndexSpec(
                name=cast(str, document["name"]),
                keys=tuple((key, int(value)) for key, value in document["key"].items()),
            )
            for document in documents
        )

    async def create_index(self, namespace: Namespace, index: IndexSpec) -> None:
        await self._database.get_collection(namespace.collection).create_index(
            list(index.keys), name=index.name
        )

    async def drop_index(self, namespace: Namespace, index_name: str) -> None:
        await self._database.get_collection(namespace.collection).drop_index(index_name)

