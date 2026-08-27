"""R10 known-counter and successful-throughput semantics."""

from app.metrics.collector import OperationMeasurement, ServerCounterSample, WorkloadMetricCollector, derive_counter_deltas


def test_successful_throughput_excludes_timeouts_and_percentiles_exclude_failures() -> None:
    collector = WorkloadMetricCollector()
    collector._started_at -= 10  # deterministic ten-second telemetry window
    for _ in range(90):
        collector.record(OperationMeasurement(10, "read"))
    for _ in range(10):
        collector.record(OperationMeasurement(9_999, "read", timed_out=True))
    snapshot = collector.snapshot({}, None)
    assert 8.9 <= snapshot.throughput_per_second <= 9.1
    assert snapshot.timeout_count == 10
    assert snapshot.p99_latency_ms == 10


def test_cumulative_counters_are_differenced_into_canonical_units() -> None:
    start = ServerCounterSample(10, 100, 40, 100, 20, 100, 1_000, 2_000)
    end = ServerCounterSample(30, 150, 60, 100, 25, 100, 1_900, 2_900)
    metrics = derive_counter_deltas(start, end, 90)
    assert metrics.cpu_utilization == 0.4
    assert metrics.memory_utilization == 0.6
    assert metrics.disk_utilization == 0.25
    assert metrics.disk_io_bytes_per_op == 10
    assert metrics.network_bytes_per_op == 10
