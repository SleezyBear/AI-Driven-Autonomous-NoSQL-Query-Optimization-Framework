"""Telemetry providers ordered by safety-preserving capability preference."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, cast


class TelemetrySource(str, Enum):
    """The normalized origin of observed MongoDB query telemetry."""

    QUERY_STATS = "QUERY_STATS"
    DIAGNOSTIC_LOG = "DIAGNOSTIC_LOG"
    PROFILER = "PROFILER"
    CURRENT_OP = "CURRENT_OP"


@dataclass(frozen=True)
class TelemetryObservation:
    """Normalized telemetry without literal predicate values."""

    source: TelemetrySource
    operation_count: int
    normalized_shape: str


class MongoTelemetryDatabase(Protocol):
    """The restricted database operations used by MongoDB telemetry providers."""

    async def command(self, command: dict[str, Any]) -> dict[str, Any]:
        """Run one fixed metadata command."""

    def aggregate(self, pipeline: list[dict[str, Any]], **kwargs: Any) -> Any:
        """Return an asynchronous aggregation cursor for fixed telemetry pipelines."""


class TelemetryProvider(ABC):
    """A read-only provider of normalized telemetry observations."""

    source: TelemetrySource

    @abstractmethod
    async def available(self) -> bool:
        """Return whether this provider can safely produce observations."""

    @abstractmethod
    async def collect(self) -> tuple[TelemetryObservation, ...]:
        """Collect normalized observations without enabling server features."""


class QueryStatsTelemetryProvider(TelemetryProvider):
    """Read existing `$queryStats` telemetry where the server permits it."""

    source = TelemetrySource.QUERY_STATS

    def __init__(self, database: MongoTelemetryDatabase) -> None:
        self._database = database

    async def available(self) -> bool:
        try:
            await self._database.command({"getParameter": 1, "internalQueryStatsRateLimit": 1})
        except Exception:
            return False
        return True

    async def collect(self) -> tuple[TelemetryObservation, ...]:
        cursor = self._database.aggregate([{"$queryStats": {}}], maxTimeMS=1_000)
        documents = await cursor.to_list(length=100)
        return tuple(
            TelemetryObservation(
                source=self.source,
                operation_count=int(document.get("execCount", 0)),
                normalized_shape=str(document.get("key", {})),
            )
            for document in documents
        )


class DiagnosticLogTelemetryProvider(TelemetryProvider):
    """Use a configured read-only diagnostic-log reader when query stats is unavailable."""

    source = TelemetrySource.DIAGNOSTIC_LOG

    def __init__(self, lines: tuple[str, ...]) -> None:
        self._lines = lines

    async def available(self) -> bool:
        return bool(self._lines)

    async def collect(self) -> tuple[TelemetryObservation, ...]:
        return tuple(
            TelemetryObservation(source=self.source, operation_count=1, normalized_shape=line)
            for line in self._lines
        )


class ProfilerTelemetryProvider(TelemetryProvider):
    """Read profiler data only when profiling is already enabled by a human."""

    source = TelemetrySource.PROFILER

    def __init__(self, database: MongoTelemetryDatabase) -> None:
        self._database = database
        self._enabled = False

    async def available(self) -> bool:
        status = await self._database.command({"profile": -1})
        self._enabled = cast(int, status.get("was", 0)) > 0
        return self._enabled

    async def collect(self) -> tuple[TelemetryObservation, ...]:
        if not self._enabled:
            return ()
        cursor = self._database.aggregate(
            [{"$match": {"ns": {"$exists": True}}}, {"$limit": 100}], collection="system.profile"
        )
        documents = await cursor.to_list(length=100)
        return tuple(
            TelemetryObservation(
                source=self.source,
                operation_count=1,
                normalized_shape=str(document.get("op", "unknown")),
            )
            for document in documents
        )


class CurrentOpTelemetryProvider(TelemetryProvider):
    """Use active-operation telemetry only as the final fallback."""

    source = TelemetrySource.CURRENT_OP

    def __init__(self, database: MongoTelemetryDatabase) -> None:
        self._database = database

    async def available(self) -> bool:
        try:
            await self._database.command({"currentOp": 1, "$all": False})
        except Exception:
            return False
        return True

    async def collect(self) -> tuple[TelemetryObservation, ...]:
        result = await self._database.command({"currentOp": 1, "$all": False})
        in_progress = cast(list[dict[str, Any]], result.get("inprog", []))
        return tuple(
            TelemetryObservation(
                source=self.source,
                operation_count=1,
                normalized_shape=str(operation.get("op", "unknown")),
            )
            for operation in in_progress
        )


class TelemetryCoordinator:
    """Select the first safely available provider in the frozen preference order."""

    def __init__(self, providers: tuple[TelemetryProvider, ...]) -> None:
        self._providers = providers

    async def select_provider(self) -> TelemetryProvider | None:
        """Return the first available provider; never alter server telemetry configuration."""
        for provider in self._providers:
            if await provider.available():
                return provider
        return None

