"""Frozen Phase-15 profile and protected-metric policy values."""

from __future__ import annotations

from app.admission.models import BenchmarkProfile, ComparisonMode, MetricDirection, MetricPolicy, ProfileSettings

PROFILES = {
    BenchmarkProfile.SMOKE: ProfileSettings(False, 5, 10, 1000, 0.95, candidate_pairs=3),
    BenchmarkProfile.AUTONOMOUS: ProfileSettings(True, 30, 60, 10000, 0.95, pilot_aa_pairs=10, minimum_candidate_pairs=10, maximum_candidate_pairs=30),
    BenchmarkProfile.PUBLICATION: ProfileSettings(False, 60, 120, 10000, 0.95, pilot_aa_pairs=12, minimum_candidate_pairs=15, maximum_candidate_pairs=40),
}

DEFAULT_POLICIES = {
    "p50_latency_ms": MetricPolicy("p50_latency_ms", MetricDirection.LOWER_IS_BETTER, ComparisonMode.LOG_RATIO, 0.03, 25),
    "p95_latency_ms": MetricPolicy("p95_latency_ms", MetricDirection.LOWER_IS_BETTER, ComparisonMode.LOG_RATIO, 0.03, 50),
    "p99_latency_ms": MetricPolicy("p99_latency_ms", MetricDirection.LOWER_IS_BETTER, ComparisonMode.LOG_RATIO, 0.05, 100),
    "throughput_ops_s": MetricPolicy("throughput_ops_s", MetricDirection.HIGHER_IS_BETTER, ComparisonMode.LOG_RATIO, 0.03),
    "read_p95_latency_ms": MetricPolicy("read_p95_latency_ms", MetricDirection.LOWER_IS_BETTER, ComparisonMode.LOG_RATIO, 0.03, 50),
    "write_p95_latency_ms": MetricPolicy("write_p95_latency_ms", MetricDirection.LOWER_IS_BETTER, ComparisonMode.LOG_RATIO, 0.03, 50),
    "cpu_utilization": MetricPolicy("cpu_utilization", MetricDirection.LOWER_IS_BETTER, ComparisonMode.ABSOLUTE_DELTA, 0.10, 0.03, 0.80, 0.10),
    "memory_utilization": MetricPolicy("memory_utilization", MetricDirection.LOWER_IS_BETTER, ComparisonMode.ABSOLUTE_DELTA, 0.10, 0.03, 0.85, 0.10),
    "disk_utilization": MetricPolicy("disk_utilization", MetricDirection.LOWER_IS_BETTER, ComparisonMode.ABSOLUTE_DELTA, 0.05, 0.02, 0.80, 0.10),
    "replication_lag_ms": MetricPolicy("replication_lag_ms", MetricDirection.LOWER_IS_BETTER, ComparisonMode.ABSOLUTE_DELTA, 0.10, 250, 5000, 0.10),
    "network_bytes_per_op": MetricPolicy("network_bytes_per_op", MetricDirection.LOWER_IS_BETTER, ComparisonMode.LOG_RATIO, 0.05),
    "disk_io_bytes_per_op": MetricPolicy("disk_io_bytes_per_op", MetricDirection.LOWER_IS_BETTER, ComparisonMode.LOG_RATIO, 0.05),
    "documents_examined_per_returned": MetricPolicy("documents_examined_per_returned", MetricDirection.LOWER_IS_BETTER, ComparisonMode.LOG_RATIO, 0.10),
    "keys_examined_per_returned": MetricPolicy("keys_examined_per_returned", MetricDirection.LOWER_IS_BETTER, ComparisonMode.LOG_RATIO, 0.10),
    "lock_wait_ms_per_op": MetricPolicy("lock_wait_ms_per_op", MetricDirection.LOWER_IS_BETTER, ComparisonMode.LOG_RATIO, 0.05),
}
