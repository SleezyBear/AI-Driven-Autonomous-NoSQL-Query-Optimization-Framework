"""Phase 14 acceptance tests for equivalent-state paired benchmarks."""

from app.metrics.collector import MetricSnapshot
from app.workloads.snapshots import EnvironmentFingerprint
from benchmarks.commercebench import CommerceBench, WorkloadProfile
from benchmarks.runner import BenchmarkArm, BenchmarkRunner, InMemoryBenchmarkResultStore


def _metrics() -> MetricSnapshot:
    return MetricSnapshot(None, None, None, 0, 0, 0, None, None, None, None, None, None, 0, 0, 0, 0, 0, 0)


class RecordingRestorer:
    def __init__(self) -> None:
        self.events: list[str] = []

    def restore(self, snapshot: object) -> str:
        self.events.append("restore")
        return getattr(snapshot, "fingerprint")


def test_write_pair_restores_equivalent_state_and_persists_required_evidence() -> None:
    restorer = RecordingRestorer()
    store = InMemoryBenchmarkResultStore()
    runner = BenchmarkRunner(restorer, store)
    snapshot = CommerceBench().reset(WorkloadProfile.SMOKE)

    baseline, candidate = runner.compare(
        "pair-001",
        snapshot,
        EnvironmentFingerprint.from_mapping({"mongo": "8.0"}),
        lambda: _measure(restorer, "baseline"),
        lambda: _measure(restorer, "candidate"),
    )

    assert restorer.events == ["restore", "baseline", "restore", "candidate"]
    assert baseline.initial_dataset_fingerprint == candidate.initial_dataset_fingerprint == snapshot.fingerprint
    assert [record.arm for record in store.records] == [BenchmarkArm.BASELINE, BenchmarkArm.CANDIDATE]
    assert all(record.pair_id == "pair-001" for record in store.records)
    assert all(record.seed == 42 for record in store.records)
    assert all(record.dataset_fingerprint == snapshot.fingerprint for record in store.records)
    assert all(record.metrics == _metrics() for record in store.records)


def _measure(restorer: RecordingRestorer, arm: str) -> MetricSnapshot:
    restorer.events.append(arm)
    return _metrics()
