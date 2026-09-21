"""MongoDB implementation of the typed DatabaseAdapter contract."""

from __future__ import annotations

from collections.abc import Mapping
from inspect import isawaitable
from typing import Any, Protocol, cast

from app.adapters.contracts import DatabaseAdapter, IndexSpec, Namespace, QuerySettingsIndexHint


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

    def aggregate(self, pipeline: list[dict[str, object]]) -> Any:
        """Return the query-settings aggregation cursor."""

    async def command(self, command: dict[str, object]) -> Mapping[str, object]:
        """Run the adapter's fixed query-settings command document."""


class MongoClientProtocol(Protocol):
    """The restricted client operation used to select the configured database."""

    def get_database(self, name: str) -> MongoDatabaseProtocol:
        """Return the configured database."""


class MongoDBAdapter(DatabaseAdapter):
    """Use an injected async Mongo client through typed metadata/index operations only."""

    def __init__(self, client: MongoClientProtocol, database_name: str) -> None:
        self._database = client.get_database(database_name)
        self._admin_database = client.get_database("admin")
        self._database_name = database_name

    async def list_namespaces(self) -> tuple[Namespace, ...]:
        names = await self._database.list_collection_names()
        return tuple(Namespace(collection=name) for name in sorted(names))

    async def list_indexes(self, namespace: Namespace) -> tuple[IndexSpec, ...]:
        cursor = self._database.get_collection(namespace.collection).list_indexes()
        if isawaitable(cursor):
            cursor = await cursor
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

    async def get_query_settings_index_hint(
        self, namespace: Namespace, query_shape_hash: str
    ) -> QuerySettingsIndexHint | None:
        # MongoDB requires $querySettings to run as aggregate:1 on admin.
        cursor = self._admin_database.aggregate([{"$querySettings": {}}])
        if isawaitable(cursor):
            cursor = await cursor
        settings_documents = [document async for document in cursor]
        matching = [
            document
            for document in settings_documents
            if isinstance(document, Mapping) and document.get("queryShapeHash") == query_shape_hash
        ]
        if not matching:
            return None
        if len(matching) != 1:
            raise ValueError("ambiguous query-settings state")
        settings = matching[0].get("settings")
        if not isinstance(settings, Mapping) or set(settings) != {"indexHints"}:
            raise ValueError("existing human query setting is outside the allowedIndexes boundary")
        index_hints = settings["indexHints"]
        hints = index_hints if isinstance(index_hints, list) else [index_hints]
        relevant = [
            hint
            for hint in hints
            if isinstance(hint, Mapping)
            and hint.get("ns") == {"db": self._database_name, "coll": namespace.collection}
        ]
        if len(relevant) != 1 or not isinstance(relevant[0].get("allowedIndexes"), list):
            raise ValueError("query setting is not one exact allowedIndexes hint")
        allowed_indexes = tuple(relevant[0]["allowedIndexes"])
        if not allowed_indexes or not all(isinstance(item, str) and item for item in allowed_indexes):
            raise ValueError("query setting contains an unsupported allowedIndexes value")
        return QuerySettingsIndexHint(cast(tuple[str, ...], allowed_indexes))

    async def set_query_settings_index_hint(
        self, namespace: Namespace, query_shape_hash: str, hint: QuerySettingsIndexHint | None
    ) -> None:
        if hint is None:
            await self._admin_database.command({"removeQuerySettings": query_shape_hash})
            return
        await self._admin_database.command(
            {
                "setQuerySettings": query_shape_hash,
                "settings": {
                    "indexHints": [
                        {
                            "ns": {"db": self._database_name, "coll": namespace.collection},
                            "allowedIndexes": list(hint.allowed_indexes),
                        }
                    ]
                },
            }
        )
