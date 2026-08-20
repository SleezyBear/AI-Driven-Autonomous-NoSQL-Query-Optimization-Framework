"""Phase 12 acceptance tests for workload snapshots."""

from dataclasses import FrozenInstanceError

import pytest

from app.metrics.collector import MetricSnapshot, OperationMeasurement
from app.workloads.snapshots import EnvironmentFingerprint, QueryShapeWorkload, WorkloadSnapshotBuilder


def _metrics() -> MetricSnapshot:
    return MetricSnapshot(None, None, None, 0, 0, 0, None, None, None, None, None, None, 0, 0, 0, 0, 0, 0)


def test_90_9_1_distribution_protects_all_query_shapes() -> None:
    snapshot = WorkloadSnapshotBuilder.build(
        measurements=[OperationMeasurement(1, "read")] * 100,
        query_shapes=[
            QueryShapeWorkload("shape-90", 90, 90),
            QueryShapeWorkload("shape-9", 9, 9),
            QueryShapeWorkload("shape-1", 1, 1),
        ],
        global_metrics=_metrics(),
        environment_fingerprint=EnvironmentFingerprint.from_mapping({"mongo_version": "8.0", "fcv": "8.0"}),
    )

    assert snapshot.critical_query_shapes == ("shape-90", "shape-9", "shape-1")
    assert [share.fraction for share in snapshot.query_shape_shares] == [0.9, 0.09, 0.01]
    assert [share.fraction for share in snapshot.execution_time_shares] == [0.9, 0.09, 0.01]
    assert snapshot.operation_mix[0].name == "read"
    assert snapshot.operation_mix[0].fraction == 1.0


def test_explicit_or_manual_critical_shapes_are_protected_below_one_percent() -> None:
    snapshot = WorkloadSnapshotBuilder.build(
        measurements=[],
        query_shapes=[
            QueryShapeWorkload("affected", 0, 0, explicitly_affected=True),
            QueryShapeWorkload("manual", 0, 0, manually_critical=True),
            QueryShapeWorkload("ordinary", 0, 0),
        ],
        global_metrics=_metrics(),
        environment_fingerprint=EnvironmentFingerprint.from_mapping({}),
    )

    assert snapshot.critical_query_shapes == ("affected", "manual")


def test_snapshot_and_environment_fingerprint_are_immutable() -> None:
    source_facts = {"topology": "replica-set"}
    fingerprint = EnvironmentFingerprint.from_mapping(source_facts)
    source_facts["topology"] = "mutated"
    snapshot = WorkloadSnapshotBuilder.build([], [], _metrics(), fingerprint)

    assert snapshot.environment_fingerprint.facts == (("topology", "replica-set"),)
    with pytest.raises(FrozenInstanceError):
        snapshot.critical_query_shapes = ("other",)  # type: ignore[misc]
