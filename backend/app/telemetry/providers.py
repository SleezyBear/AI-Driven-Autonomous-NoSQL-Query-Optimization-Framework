"""Read-only MongoDB telemetry providers that emit literal-free structured observations."""

from __future__ import annotations

import json
import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol, cast

from app.query_shapes.registry import canonicalize


class TelemetrySource(str, Enum):
    QUERY_STATS = "QUERY_STATS"
    DIAGNOSTIC_LOG = "DIAGNOSTIC_LOG"
    PROFILER = "PROFILER"
    CURRENT_OP = "CURRENT_OP"


@dataclass(frozen=True)
class TelemetryObservation:
    """A namespace-qualified, literal-free telemetry record."""

    source: TelemetrySource
    operation_count: int
    database: str
    collection: str
    operation: str
    normalized_shape: dict[str, Any]
    successful_operation_count: int | None = None
    failure_count: int | None = None
    timeout_count: int | None = None
    aggregate_execution_time_ms: float | None = None

    @property
    def namespace(self) -> str:
        """Canonical database-plus-collection namespace used throughout telemetry."""
        return f"{self.database}.{self.collection}"


class MongoTelemetryDatabase(Protocol):
    async def command(self, command: dict[str, Any]) -> dict[str, Any]: ...
    async def aggregate(self, pipeline: list[dict[str, Any]], **kwargs: Any) -> Any: ...


class TelemetryProvider(ABC):
    source: TelemetrySource

    @abstractmethod
    async def available(self) -> bool: ...

    @abstractmethod
    async def collect(self) -> tuple[TelemetryObservation, ...]: ...


class QueryStatsTelemetryProvider(TelemetryProvider):
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
        cursor = await _aggregate(self._database, [{"$queryStats": {}}], maxTimeMS=1_000)
        documents = await cursor.to_list(length=100)
        return tuple(observation for document in documents if (observation := _from_query_stats(document)) is not None)


class DiagnosticLogTelemetryProvider(TelemetryProvider):
    """Parse only structured diagnostic events; raw log lines are never retained."""

    source = TelemetrySource.DIAGNOSTIC_LOG

    def __init__(self, lines: tuple[str, ...]) -> None:
        self._lines = lines

    async def available(self) -> bool:
        return any(_parse_diagnostic_line(line) is not None for line in self._lines)

    async def collect(self) -> tuple[TelemetryObservation, ...]:
        return tuple(observation for line in self._lines if (observation := _parse_diagnostic_line(line)) is not None)


class ProfilerTelemetryProvider(TelemetryProvider):
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
        cursor = await _aggregate(self._database, [{"$match": {"ns": {"$exists": True}}}, {"$limit": 100}], collection="system.profile")
        documents = await cursor.to_list(length=100)
        return tuple(observation for document in documents if (observation := _from_command_document(self.source, document)) is not None)


class CurrentOpTelemetryProvider(TelemetryProvider):
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
        return tuple(observation for operation in in_progress if (observation := _from_command_document(self.source, operation)) is not None)


class TelemetryCoordinator:
    """Select the first safely available provider in the frozen preference order."""

    def __init__(self, providers: tuple[TelemetryProvider, ...]) -> None:
        self._providers = providers

    async def select_provider(self) -> TelemetryProvider | None:
        for provider in self._providers:
            if await provider.available():
                return provider
        return None


def _from_query_stats(document: Mapping[str, Any]) -> TelemetryObservation | None:
    key = document.get("key")
    if not isinstance(key, Mapping):
        return None
    namespace = _namespace(key.get("ns"))
    if namespace is None:
        return None
    shape = key.get("queryShape", key)
    query_shape = key.get("queryShape")
    operation = str(query_shape.get("command", "unknown")) if isinstance(query_shape, Mapping) else "unknown"
    count = int(document.get("execCount", 0))
    total_micros = _numeric(document.get("totalExecMicros"))
    return _observation(
        TelemetrySource.QUERY_STATS,
        count,
        namespace,
        operation,
        shape,
        successful_operation_count=count,
        aggregate_execution_time_ms=None if total_micros is None else total_micros / 1_000,
    )


def _parse_diagnostic_line(line: str) -> TelemetryObservation | None:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(event, Mapping):
        return None
    attributes = event.get("attr")
    if not isinstance(attributes, Mapping):
        return None
    return _from_command_document(TelemetrySource.DIAGNOSTIC_LOG, attributes)


def _from_command_document(source: TelemetrySource, document: Mapping[str, Any]) -> TelemetryObservation | None:
    namespace = _namespace(document.get("ns"))
    if namespace is None:
        return None
    command = document.get("command", document.get("query", {}))
    if not isinstance(command, Mapping):
        command = {}
    reported_operation = document.get("op", document.get("type"))
    operation = (
        _operation_from_command(command)
        if reported_operation in {None, "command"}
        else str(reported_operation)
    )
    duration = _numeric(document.get("durationMillis", document.get("millis")))
    if duration is None:
        microseconds = _numeric(document.get("microsecs_running"))
        duration = None if microseconds is None else microseconds / 1_000
    completed = source in {TelemetrySource.DIAGNOSTIC_LOG, TelemetrySource.PROFILER}
    failed = any(name in document for name in ("errCode", "errName", "errMsg"))
    timeout = str(document.get("errName", "")).lower() in {
        "maxtimemsexpired",
        "networktimeoutexception",
    }
    return _observation(
        source,
        1,
        namespace,
        operation,
        command,
        successful_operation_count=int(not failed) if completed else None,
        failure_count=int(failed) if completed else None,
        timeout_count=int(timeout) if completed else None,
        aggregate_execution_time_ms=duration,
    )


def _observation(
    source: TelemetrySource,
    count: int,
    namespace: tuple[str, str],
    operation: str,
    shape: Any,
    *,
    successful_operation_count: int | None = None,
    failure_count: int | None = None,
    timeout_count: int | None = None,
    aggregate_execution_time_ms: float | None = None,
) -> TelemetryObservation:
    normalized = canonicalize(shape)
    assert isinstance(normalized, dict)
    return TelemetryObservation(
        source,
        max(count, 0),
        namespace[0],
        namespace[1],
        operation,
        normalized,
        successful_operation_count,
        failure_count,
        timeout_count,
        aggregate_execution_time_ms,
    )


def _namespace(value: Any) -> tuple[str, str] | None:
    if isinstance(value, Mapping):
        database, collection = value.get("db"), value.get("coll")
        if isinstance(database, str) and isinstance(collection, str) and database and collection:
            return database, collection
    if isinstance(value, str) and "." in value:
        database, collection = value.split(".", 1)
        if database and collection:
            return database, collection
    return None


def _operation_from_command(command: Mapping[str, Any]) -> str:
    return next((str(name) for name in ("find", "aggregate", "update", "delete", "insert") if name in command), "unknown")


def _numeric(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


async def _aggregate(database: MongoTelemetryDatabase, pipeline: list[dict[str, Any]], **kwargs: Any) -> Any:
    """Accept the project's async PyMongo API and existing cursor-style doubles."""
    result = database.aggregate(pipeline, **kwargs)
    return await result if inspect.isawaitable(result) else result
