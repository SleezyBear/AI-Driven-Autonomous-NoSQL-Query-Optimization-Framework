"""Phase 14 acceptance tests for equivalent-state paired benchmarks."""

from app.metrics.collector import MetricSnapshot
from app.workloads.snapshots import EnvironmentFingerprint
from benchmarks.commercebench import CommerceBench, WorkloadProfile
from benchmarks.hardware import HardwareManifest
from benchmarks.runner import BenchmarkArm, BenchmarkRunner, InMemoryBenchmarkResultStore


def _metrics() -> MetricSnapshot:
    return MetricSnapshot(None, None, None, 0, 0, 0, None, None, None, None, None, None, 0, 0, 0, 0, 0, 0)


class RecordingRestorer:
    def __init__(self) -> None:
        self.events: list[str] = []

    def restore(self, snapshot: object) -> str:
        self.events.append("restore")
        return getattr(snapshot, "fingerprint")


class FixedHardwareManifestCollector:
    def collect(self) -> HardwareManifest:
        return HardwareManifest(
            macos_version="15.7.7",
            cpu_model="Intel Core i7-8850H",
            architecture="x86_64",
            physical_cores=6,
            logical_cpus=12,
            ram_bytes=16 * 1024**3,
            docker_version="28.0.0",
            docker_allocated_cpus=6,
            docker_allocated_ram_bytes=8 * 1024**3,
            mongodb_version="8.0.0",
            postgresql_version="17.0",
            python_version="3.10.20",
            numpy_version="1.26.4",
            scipy_version="1.12.0",
            pymongo_version="4.13.2",
            ollama_version="0.32.9",
            chat_model="gemma4:e4b",
            embedding_model="embeddinggemma",
        )


def test_write_pair_restores_equivalent_state_and_persists_required_evidence() -> None:
    restorer = RecordingRestorer()
    store = InMemoryBenchmarkResultStore()
    runner = BenchmarkRunner(restorer, store, FixedHardwareManifestCollector())
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
    assert baseline.hardware_manifest == candidate.hardware_manifest
    assert baseline.hardware_manifest.cpu_model == "Intel Core i7-8850H"


def _measure(restorer: RecordingRestorer, arm: str) -> MetricSnapshot:
    restorer.events.append(arm)
    return _metrics()
