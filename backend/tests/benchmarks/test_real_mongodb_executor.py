"""Unit checks for real-executor evidence semantics without requiring Docker."""

from benchmarks.mongodb_executor import RealBenchmarkMeasurement, _percentile


def test_percentiles_require_successful_latency_samples() -> None:
    assert _percentile([], 95) is None
    assert _percentile([1.0, 3.0], 50) == 2.0


def test_real_measurement_exposes_successes_failures_and_timeouts_separately() -> None:
    measurement = RealBenchmarkMeasurement(90, 2, 8, 10.0, 9.0, 1.0, 2.0, 3.0, object())  # type: ignore[arg-type]

    assert measurement.successful_operations == 90
    assert measurement.error_count == 2
    assert measurement.timeout_count == 8
    assert measurement.throughput_successful_ops_per_second == 9.0
