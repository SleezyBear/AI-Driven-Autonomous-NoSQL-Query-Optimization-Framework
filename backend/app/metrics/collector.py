"""Normalized metrics from recorded operations and read-only MongoDB server state."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, cast

import numpy as np


@dataclass(frozen=True)
class OperationMeasurement:
    """One completed database operation's normalized timing and scan evidence."""

    duration_ms: float
    operation_type: str
    documents_examined: int = 0
    documents_returned: int = 0
    keys_examined: int = 0
    lock_wait_ms: float = 0.0
    error: bool = False
    timed_out: bool = False


@dataclass(frozen=True)
class MetricSnapshot:
    """The complete Phase 11 metric set for one immutable collection window."""

    p50_latency_ms: float | None
    p95_latency_ms: float | None
    p99_latency_ms: float | None
    throughput_per_second: float
    read_throughput_per_second: float
    write_throughput_per_second: float
    cpu_time_us: float | None
    memory_bytes: float | None
    disk_bytes: float | None
    disk_io_bytes: float | None
    network_io_bytes: float | None
    replication_lag_seconds: float | None
    documents_examined: int
    documents_returned: int
    keys_examined: int
    lock_wait_ms: float
    error_count: int
    timeout_count: int

    @property
    def latency_milliseconds(self) -> tuple[float | None, float | None, float | None]:
        """Successful-operation p50/p95/p99 latencies in milliseconds."""
        return (self.p50_latency_ms, self.p95_latency_ms, self.p99_latency_ms)

    @property
    def replication_lag_milliseconds(self) -> float | None:
        return None if self.replication_lag_seconds is None else self.replication_lag_seconds * 1_000


@dataclass(frozen=True)
class ServerCounterSample:
    """Cumulative server counters captured at one end of a telemetry window."""

    cpu_busy: float
    cpu_total: float
    memory_used_bytes: float
    memory_total_bytes: float
    disk_used_bytes: float
    disk_total_bytes: float
    disk_io_bytes: float
    network_bytes: float


@dataclass(frozen=True)
class CounterDeltas:
    """Canonical rate/utilization values differenced from window start and end."""

    cpu_utilization: float
    memory_utilization: float
    disk_utilization: float
    disk_io_bytes_per_op: float
    network_bytes_per_op: float


def derive_counter_deltas(window_start: ServerCounterSample, window_end: ServerCounterSample, successful_operations: int) -> CounterDeltas:
    """Difference cumulative counters; never treat an absolute counter as a window metric."""
    operations = max(successful_operations, 1)
    cpu_total = max(window_end.cpu_total - window_start.cpu_total, 0.0)
    cpu_busy = max(window_end.cpu_busy - window_start.cpu_busy, 0.0)
    return CounterDeltas(
        cpu_utilization=cpu_busy / cpu_total if cpu_total else 0.0,
        memory_utilization=_ratio(window_end.memory_used_bytes, window_end.memory_total_bytes),
        disk_utilization=_ratio(window_end.disk_used_bytes, window_end.disk_total_bytes),
        disk_io_bytes_per_op=max(window_end.disk_io_bytes - window_start.disk_io_bytes, 0.0) / operations,
        network_bytes_per_op=max(window_end.network_bytes - window_start.network_bytes, 0.0) / operations,
    )


def _ratio(numerator: float, denominator: float) -> float:
    return min(1.0, max(0.0, numerator / denominator)) if denominator > 0 else 0.0


class WorkloadMetricCollector:
    """Record completed workload operations and produce normalized percentiles and rates."""

    def __init__(self) -> None:
        self._started_at = perf_counter()
        self._measurements: list[OperationMeasurement] = []

    def record(self, measurement: OperationMeasurement) -> None:
        """Record an already-completed operation without retaining predicates or documents."""
        self._measurements.append(measurement)

    def snapshot(self, server_status: dict[str, Any], replication_lag_seconds: float | None) -> MetricSnapshot:
        """Produce all required metrics from workload records and server status data."""
        elapsed_seconds = max(perf_counter() - self._started_at, 0.001)
        successful = [measurement for measurement in self._measurements if not measurement.error and not measurement.timed_out]
        durations = [measurement.duration_ms for measurement in successful]
        reads = sum(measurement.operation_type == "read" for measurement in successful)
        writes = sum(measurement.operation_type == "write" for measurement in successful)
        memory = cast(dict[str, Any], server_status.get("mem", {}))
        network = cast(dict[str, Any], server_status.get("network", {}))
        extra_info = cast(dict[str, Any], server_status.get("extra_info", {}))
        wired_tiger = cast(dict[str, Any], server_status.get("wiredTiger", {}))
        cache = cast(dict[str, Any], wired_tiger.get("cache", {}))
        log = cast(dict[str, Any], wired_tiger.get("log", {}))

        return MetricSnapshot(
            p50_latency_ms=self._percentile(durations, 50),
            p95_latency_ms=self._percentile(durations, 95),
            p99_latency_ms=self._percentile(durations, 99),
            throughput_per_second=len(successful) / elapsed_seconds,
            read_throughput_per_second=reads / elapsed_seconds,
            write_throughput_per_second=writes / elapsed_seconds,
            cpu_time_us=self._number(extra_info.get("user_time_us"))
            + self._number(extra_info.get("system_time_us")),
            memory_bytes=self._number(memory.get("resident")) * 1024 * 1024,
            disk_bytes=self._number(cache.get("bytes currently in the cache")),
            disk_io_bytes=self._number(log.get("log bytes written")),
            network_io_bytes=self._number(network.get("bytesIn")) + self._number(network.get("bytesOut")),
            replication_lag_seconds=replication_lag_seconds,
            documents_examined=sum(item.documents_examined for item in self._measurements),
            documents_returned=sum(item.documents_returned for item in self._measurements),
            keys_examined=sum(item.keys_examined for item in self._measurements),
            lock_wait_ms=sum(item.lock_wait_ms for item in self._measurements),
            error_count=sum(item.error for item in self._measurements),
            timeout_count=sum(item.timed_out for item in self._measurements),
        )

    @staticmethod
    def _percentile(values: list[float], percentile: int) -> float | None:
        if not values:
            return None
        return float(np.percentile(values, percentile))

    @staticmethod
    def _number(value: Any) -> float:
        return float(value) if isinstance(value, int | float) else 0.0
