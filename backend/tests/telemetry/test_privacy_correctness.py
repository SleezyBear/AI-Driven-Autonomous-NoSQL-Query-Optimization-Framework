"""Phase R11 telemetry structure and strict privacy checks."""

from __future__ import annotations

import json

import pytest

from app.security.privacy import PrivacyBoundary, PrivacyMode
from app.telemetry.providers import (
    CurrentOpTelemetryProvider,
    DiagnosticLogTelemetryProvider,
    ProfilerTelemetryProvider,
    QueryStatsTelemetryProvider,
)


CANARY = "canary-email-very-private@example.test"


class Cursor:
    def __init__(self, documents: list[dict[str, object]]) -> None:
        self._documents = documents

    async def to_list(self, length: int) -> list[dict[str, object]]:
        return self._documents[:length]


class Mongo8LikeDatabase:
    async def command(self, command: dict[str, object]) -> dict[str, object]:
        return {"internalQueryStatsRateLimit": 1}

    def aggregate(self, pipeline: list[dict[str, object]], **kwargs: object) -> Cursor:
        return Cursor(
            [
                {
                    "key": {
                        "ns": {"db": "commerce", "coll": "orders"},
                        "queryShape": {"command": "find", "filter": {"customer_email": CANARY}},
                    },
                    "execCount": 4,
                }
            ]
        )


class Mongo8FallbackDatabase:
    async def command(self, command: dict[str, object]) -> dict[str, object]:
        if "profile" in command:
            return {"was": 1}
        if "currentOp" in command:
            return {"inprog": [{"ns": "commerce.orders", "op": "query", "command": {"find": "orders", "filter": {"customer_email": CANARY}}}]}
        return {}

    def aggregate(self, pipeline: list[dict[str, object]], **kwargs: object) -> Cursor:
        return Cursor([{"ns": "commerce.orders", "op": "query", "command": {"find": "orders", "filter": {"customer_email": CANARY}}}])


@pytest.mark.asyncio
async def test_mongodb_8_query_stats_is_namespace_qualified_and_literal_free() -> None:
    observation = (await QueryStatsTelemetryProvider(Mongo8LikeDatabase()).collect())[0]

    assert observation.namespace == "commerce.orders"
    assert observation.operation == "find"
    assert observation.operation_count == 4
    assert CANARY not in json.dumps(observation.normalized_shape)
    assert observation.normalized_shape["filter"]["customer_email"] == "<string>"


@pytest.mark.asyncio
async def test_diagnostic_logs_are_structured_and_raw_lines_are_never_persistable() -> None:
    raw_line = json.dumps(
        {
            "msg": "Slow query",
            "attr": {
                "type": "command",
                "ns": "commerce.orders",
                "command": {"find": "orders", "filter": {"customer_email": CANARY}},
                "durationMillis": 125,
            },
        }
    )
    provider = DiagnosticLogTelemetryProvider((raw_line, f"unstructured {CANARY}"))

    observations = await provider.collect()

    assert len(observations) == 1
    assert observations[0].namespace == "commerce.orders"
    assert observations[0].operation == "find"
    assert observations[0].successful_operation_count == 1
    assert observations[0].failure_count == 0
    assert observations[0].timeout_count == 0
    assert observations[0].aggregate_execution_time_ms == 125
    assert CANARY not in json.dumps(observations[0].normalized_shape)
    assert raw_line != json.dumps(observations[0].normalized_shape, sort_keys=True)


@pytest.mark.asyncio
async def test_profiler_and_current_op_mongodb_8_documents_are_literal_free() -> None:
    database = Mongo8FallbackDatabase()
    profiler = ProfilerTelemetryProvider(database)
    current_op = CurrentOpTelemetryProvider(database)

    assert await profiler.available()
    profiler_observation = (await profiler.collect())[0]
    current_op_observation = (await current_op.collect())[0]

    for observation in (profiler_observation, current_op_observation):
        assert observation.namespace == "commerce.orders"
        assert CANARY not in json.dumps(observation.normalized_shape)


def test_strict_privacy_uses_keyed_hmac_for_database_collection_and_field_names() -> None:
    source = {"database": "commerce", "collection": "orders", "customer_email": CANARY}
    first = PrivacyBoundary(PrivacyMode.STRICT_HASHED, hmac_key="key-one").serialize_for_postgres(source)
    same = PrivacyBoundary(PrivacyMode.STRICT_HASHED, hmac_key="key-one").serialize_for_postgres(source)
    other = PrivacyBoundary(PrivacyMode.STRICT_HASHED, hmac_key="key-two").serialize_for_postgres(source)

    assert first == same
    assert first != other
    for literal in ("commerce", "orders", "customer_email", CANARY):
        assert literal not in first


def test_strict_privacy_rejects_an_unkeyed_hasher() -> None:
    with pytest.raises(ValueError, match="HMAC key"):
        PrivacyBoundary(PrivacyMode.STRICT_HASHED)
