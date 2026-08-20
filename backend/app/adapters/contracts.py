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

