"""Database-agnostic typed operations available to orchestration code."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Namespace:
    """An allowlisted database collection namespace."""

    collection: str


@dataclass(frozen=True)
class IndexSpec:
    """A typed index definition; it cannot encode an arbitrary database command."""

    name: str
    keys: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class QuerySettingsIndexHint:
    """The sole query-settings variant exposed to optimizer orchestration."""

    allowed_indexes: tuple[str, ...]


class DatabaseAdapter(ABC):
    """The restricted typed interface used by the optimizer core."""

    @abstractmethod
    async def list_namespaces(self) -> tuple[Namespace, ...]:
        """List collection namespaces accessible to the adapter credential."""

    @abstractmethod
    async def list_indexes(self, namespace: Namespace) -> tuple[IndexSpec, ...]:
        """List index definitions in a collection namespace."""

    @abstractmethod
    async def create_index(self, namespace: Namespace, index: IndexSpec) -> None:
        """Create an explicitly typed index definition."""

    @abstractmethod
    async def drop_index(self, namespace: Namespace, index_name: str) -> None:
        """Drop an explicitly named index definition."""

    @abstractmethod
    async def get_query_settings_index_hint(
        self, namespace: Namespace, query_shape_hash: str
    ) -> QuerySettingsIndexHint | None:
        """Read the allowed-index state for one known query shape only."""

    @abstractmethod
    async def set_query_settings_index_hint(
        self, namespace: Namespace, query_shape_hash: str, hint: QuerySettingsIndexHint | None
    ) -> None:
        """Set allowedIndexes or remove that exact query setting; no other fields exist here."""
