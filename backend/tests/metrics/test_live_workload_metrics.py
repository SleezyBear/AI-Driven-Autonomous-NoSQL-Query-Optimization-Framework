"""Live monitored-MongoDB workload test for Phase 11 metric collection."""

from __future__ import annotations

import os
from time import perf_counter

import pytest
from pymongo import AsyncMongoClient

from app.metrics.collector import OperationMeasurement, WorkloadMetricCollector


MONGODB_URI = os.environ.get(
    "MONITORED_MONGODB_URI",
    "mongodb://optimizer_observer:observer_dev_only@127.0.0.1:27017/admin?authSource=admin&directConnection=true",
)


@pytest.mark.asyncio
async def test_live_workload_produces_nonempty_metrics() -> None:
    client: AsyncMongoClient[object] = AsyncMongoClient(MONGODB_URI, serverSelectionTimeoutMS=5_000)
    collector = WorkloadMetricCollector()
    try:
        collection = client.get_database("commerce").get_collection("permission_probe")
        for _ in range(3):
            started_at = perf_counter()
            document = await collection.find_one({})
            collector.record(
                OperationMeasurement(
                    duration_ms=(perf_counter() - started_at) * 1_000,
                    operation_type="read",
                    documents_examined=1,
                    documents_returned=1 if document is not None else 0,
                )
            )
        server_status = await client.get_database("admin").command({"serverStatus": 1})
        snapshot = collector.snapshot(server_status, replication_lag_seconds=0.0)
    finally:
        await client.close()

    assert snapshot.p50_latency_ms is not None
    assert snapshot.p95_latency_ms is not None
    assert snapshot.p99_latency_ms is not None
    assert snapshot.throughput_per_second > 0
    assert snapshot.read_throughput_per_second > 0
    assert snapshot.documents_examined == 3
    assert snapshot.error_count == 0
    assert snapshot.timeout_count == 0

