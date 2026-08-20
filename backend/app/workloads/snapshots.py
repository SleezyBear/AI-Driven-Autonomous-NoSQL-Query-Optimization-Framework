"""Build literal-free, immutable summaries of observed database workloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.metrics.collector import MetricSnapshot, OperationMeasurement


@dataclass(frozen=True)
class Share:
    """A named fraction of workload operations or execution time."""

    name: str
    fraction: float


@dataclass(frozen=True)
class QueryShapeWorkload:
    """Aggregated, literal-free activity for one registered query shape."""

    shape_hash: str
    operation_count: int
    execution_time_ms: float
    explicitly_affected: bool = False
    manually_critical: bool = False


@dataclass(frozen=True)
class EnvironmentFingerprint:
    """Stable environment facts captured with a snapshot."""

    facts: tuple[tuple[str, str], ...]

    @classmethod
    def from_mapping(cls, facts: Mapping[str, object]) -> EnvironmentFingerprint:
        """Copy and sort facts so later caller mutation cannot alter the snapshot."""
        return cls(tuple(sorted((str(key), str(value)) for key, value in facts.items())))


@dataclass(frozen=True)
class WorkloadSnapshot:
    """An immutable workload basis for later recommendation and evaluation phases."""

    operation_mix: tuple[Share, ...]
    query_shape_shares: tuple[Share, ...]
    execution_time_shares: tuple[Share, ...]
    global_metrics: MetricSnapshot
    critical_query_shapes: tuple[str, ...]
    environment_fingerprint: EnvironmentFingerprint


class WorkloadSnapshotBuilder:
    """Create immutable snapshots without retaining queries or predicate literals."""

    @staticmethod
    def build(
        measurements: tuple[OperationMeasurement, ...] | list[OperationMeasurement],
        query_shapes: tuple[QueryShapeWorkload, ...] | list[QueryShapeWorkload],
        global_metrics: MetricSnapshot,
        environment_fingerprint: EnvironmentFingerprint,
    ) -> WorkloadSnapshot:
        """Capture shares and the required protected-query policy for one time window."""
        operation_counts: dict[str, int] = {}
        for measurement in measurements:
            operation_counts[measurement.operation_type] = operation_counts.get(measurement.operation_type, 0) + 1

        total_operations = sum(shape.operation_count for shape in query_shapes)
        total_execution_time = sum(shape.execution_time_ms for shape in query_shapes)
        critical_shapes = tuple(
            shape.shape_hash
            for shape in query_shapes
            if WorkloadSnapshotBuilder._is_critical(shape, total_operations, total_execution_time)
        )

        return WorkloadSnapshot(
            operation_mix=WorkloadSnapshotBuilder._shares(operation_counts),
            query_shape_shares=tuple(
                Share(shape.shape_hash, WorkloadSnapshotBuilder._fraction(shape.operation_count, total_operations))
                for shape in query_shapes
            ),
            execution_time_shares=tuple(
                Share(shape.shape_hash, WorkloadSnapshotBuilder._fraction(shape.execution_time_ms, total_execution_time))
                for shape in query_shapes
            ),
            global_metrics=global_metrics,
            critical_query_shapes=critical_shapes,
            environment_fingerprint=environment_fingerprint,
        )

    @staticmethod
    def _shares(counts: Mapping[str, int]) -> tuple[Share, ...]:
        total = sum(counts.values())
        return tuple(Share(name, WorkloadSnapshotBuilder._fraction(count, total)) for name, count in sorted(counts.items()))

    @staticmethod
    def _is_critical(shape: QueryShapeWorkload, total_operations: int, total_execution_time: float) -> bool:
        return (
            shape.explicitly_affected
            or shape.manually_critical
            or WorkloadSnapshotBuilder._fraction(shape.operation_count, total_operations) >= 0.01
            or WorkloadSnapshotBuilder._fraction(shape.execution_time_ms, total_execution_time) >= 0.01
        )

    @staticmethod
    def _fraction(value: int | float, total: int | float) -> float:
        return float(value / total) if total else 0.0
