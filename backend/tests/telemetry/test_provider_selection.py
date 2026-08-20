"""Tests for fixed telemetry preference and profiler non-enablement."""

from __future__ import annotations

from typing import Any

import pytest

from app.telemetry.providers import (
    CurrentOpTelemetryProvider,
    DiagnosticLogTelemetryProvider,
    ProfilerTelemetryProvider,
    QueryStatsTelemetryProvider,
    TelemetryCoordinator,
    TelemetrySource,
)


class EmptyCursor:
    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return []


class FakeTelemetryDatabase:
    def __init__(self, responses: dict[str, dict[str, Any]], failures: set[str] = set()) -> None:
        self.responses = responses
        self.failures = failures
        self.commands: list[dict[str, Any]] = []

    async def command(self, command: dict[str, Any]) -> dict[str, Any]:
        self.commands.append(command)
        command_name = next(iter(command))
        if command_name in self.failures:
            raise RuntimeError(command_name)
        return self.responses.get(command_name, {})

    def aggregate(self, pipeline: list[dict[str, Any]], **kwargs: Any) -> EmptyCursor:
        return EmptyCursor()


@pytest.mark.asyncio
async def test_query_stats_is_preferred_over_all_fallbacks() -> None:
    database = FakeTelemetryDatabase(
        {"getParameter": {}, "profile": {"was": 1}, "currentOp": {"inprog": []}}
    )
    coordinator = TelemetryCoordinator(
        (
            QueryStatsTelemetryProvider(database),
            DiagnosticLogTelemetryProvider(("diagnostic observation",)),
            ProfilerTelemetryProvider(database),
            CurrentOpTelemetryProvider(database),
        )
    )

    provider = await coordinator.select_provider()

    assert provider is not None
    assert provider.source is TelemetrySource.QUERY_STATS


@pytest.mark.asyncio
async def test_diagnostic_log_is_selected_when_query_stats_is_unavailable() -> None:
    database = FakeTelemetryDatabase({}, failures={"getParameter"})
    coordinator = TelemetryCoordinator(
        (
            QueryStatsTelemetryProvider(database),
            DiagnosticLogTelemetryProvider(("diagnostic observation",)),
            ProfilerTelemetryProvider(database),
            CurrentOpTelemetryProvider(database),
        )
    )

    provider = await coordinator.select_provider()

    assert provider is not None
    assert provider.source is TelemetrySource.DIAGNOSTIC_LOG


@pytest.mark.asyncio
async def test_disabled_profiler_is_not_enabled_or_selected() -> None:
    database = FakeTelemetryDatabase(
        {"profile": {"was": 0}, "currentOp": {"inprog": []}}, failures={"getParameter"}
    )
    profiler = ProfilerTelemetryProvider(database)
    coordinator = TelemetryCoordinator(
        (QueryStatsTelemetryProvider(database), DiagnosticLogTelemetryProvider(()), profiler, CurrentOpTelemetryProvider(database))
    )

    provider = await coordinator.select_provider()

    assert provider is not None
    assert provider.source is TelemetrySource.CURRENT_OP
    assert database.commands == [
        {"getParameter": 1, "internalQueryStatsRateLimit": 1},
        {"profile": -1},
        {"currentOp": 1, "$all": False},
    ]

