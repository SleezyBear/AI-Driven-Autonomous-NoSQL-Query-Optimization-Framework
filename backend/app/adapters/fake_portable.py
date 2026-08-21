"""Portable in-memory adapter used to prove orchestration is database-independent."""

from __future__ import annotations

from app.adapters.contracts import IndexSpec, Namespace
from app.adapters.fake import FakeDatabaseAdapter


class FakePortableAdapter(FakeDatabaseAdapter):
    """A non-MongoDB-branded typed adapter that records core orchestration operations."""

    def __init__(self, namespaces: tuple[Namespace, ...] = ()) -> None:
        super().__init__(namespaces)
        self.operations: list[tuple[str, str, str]] = []

    async def create_index(self, namespace: Namespace, index: IndexSpec) -> None:
        self.operations.append(("create_index", namespace.collection, index.name))
        await super().create_index(namespace, index)

    async def drop_index(self, namespace: Namespace, index_name: str) -> None:
        self.operations.append(("drop_index", namespace.collection, index_name))
        await super().drop_index(namespace, index_name)
