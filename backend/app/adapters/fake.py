"""In-memory DatabaseAdapter implementation for deterministic contract tests."""

from __future__ import annotations

from app.adapters.contracts import DatabaseAdapter, IndexSpec, Namespace, QuerySettingsIndexHint


class FakeDatabaseAdapter(DatabaseAdapter):
    """A deterministic adapter that models only typed index metadata operations."""

    def __init__(self, namespaces: tuple[Namespace, ...] = ()) -> None:
        self._indexes: dict[str, dict[str, IndexSpec]] = {
            namespace.collection: {} for namespace in namespaces
        }
        self._query_settings: dict[tuple[str, str], QuerySettingsIndexHint] = {}

    async def list_namespaces(self) -> tuple[Namespace, ...]:
        return tuple(Namespace(collection=name) for name in sorted(self._indexes))

    async def list_indexes(self, namespace: Namespace) -> tuple[IndexSpec, ...]:
        indexes = self._indexes.get(namespace.collection, {})
        return tuple(indexes[name] for name in sorted(indexes))

    async def create_index(self, namespace: Namespace, index: IndexSpec) -> None:
        self._indexes.setdefault(namespace.collection, {})[index.name] = index

    async def drop_index(self, namespace: Namespace, index_name: str) -> None:
        self._indexes.get(namespace.collection, {}).pop(index_name, None)

    async def get_query_settings_index_hint(
        self, namespace: Namespace, query_shape_hash: str
    ) -> QuerySettingsIndexHint | None:
        return self._query_settings.get((namespace.collection, query_shape_hash))

    async def set_query_settings_index_hint(
        self, namespace: Namespace, query_shape_hash: str, hint: QuerySettingsIndexHint | None
    ) -> None:
        key = (namespace.collection, query_shape_hash)
        if hint is None:
            self._query_settings.pop(key, None)
        else:
            self._query_settings[key] = hint
