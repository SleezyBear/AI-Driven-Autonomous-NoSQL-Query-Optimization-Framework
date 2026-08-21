"""Paired benchmark execution with equivalent initial dataset state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from app.metrics.collector import MetricSnapshot
from app.workloads.snapshots import EnvironmentFingerprint
from benchmarks.commercebench import DatasetSnapshot
from benchmarks.hardware import HardwareManifest, HardwareManifestCollector, SystemHardwareManifestCollector


class BenchmarkArm(str, Enum):
    """The two arms of a controlled candidate comparison."""

    BASELINE = "baseline"
    CANDIDATE = "candidate"


class BenchmarkArmOrder(str, Enum):
    """Persisted execution order for one paired comparison."""

    AB = "AB"
    BA = "BA"


@dataclass(frozen=True)
class BenchmarkRunRecord:
    """The persisted evidence for one arm of a paired benchmark comparison."""

    pair_id: str
    arm: BenchmarkArm
    arm_order: BenchmarkArmOrder
    seed: int
    dataset_fingerprint: str
    initial_dataset_fingerprint: str
    environment_fingerprint: EnvironmentFingerprint
    hardware_manifest: HardwareManifest
    metrics: MetricSnapshot


class SnapshotRestorer(Protocol):
    """Restore a dataset and return the fingerprint of the state actually restored."""

    def restore(self, snapshot: DatasetSnapshot) -> str:
        """Restore the supplied snapshot before a measurement arm."""


class BenchmarkResultStore(Protocol):
    """Persist paired-run evidence for later statistical admission."""

    def persist(self, record: BenchmarkRunRecord) -> None:
        """Persist one benchmark arm record."""


class InMemoryBenchmarkResultStore:
    """Simple deterministic store used by local development and test execution."""

    def __init__(self) -> None:
        self.records: list[BenchmarkRunRecord] = []

    def persist(self, record: BenchmarkRunRecord) -> None:
        """Retain complete evidence for the arm."""
        self.records.append(record)


class BenchmarkRunner:
    """Run baseline/candidate pairs from equivalent restored dataset snapshots."""

    def __init__(
        self,
        restorer: SnapshotRestorer,
        result_store: BenchmarkResultStore,
        hardware_manifest_collector: HardwareManifestCollector | None = None,
    ) -> None:
        self._restorer = restorer
        self._result_store = result_store
        self._hardware_manifest_collector = hardware_manifest_collector or SystemHardwareManifestCollector()

    def compare(
        self,
        pair_id: str,
        dataset_snapshot: DatasetSnapshot,
        environment_fingerprint: EnvironmentFingerprint,
        baseline: Callable[[], MetricSnapshot],
        candidate: Callable[[], MetricSnapshot],
        arm_order: BenchmarkArmOrder = BenchmarkArmOrder.AB,
    ) -> tuple[BenchmarkRunRecord, BenchmarkRunRecord]:
        """Restore → baseline → restore → candidate and persist both measurement arms."""
        arms: tuple[tuple[BenchmarkArm, Callable[[], MetricSnapshot]], ...] = (
            (BenchmarkArm.BASELINE, baseline),
            (BenchmarkArm.CANDIDATE, candidate),
        )
        if arm_order == BenchmarkArmOrder.BA:
            arms = tuple(reversed(arms))
        hardware_manifest = self._hardware_manifest_collector.collect()
        records: dict[BenchmarkArm, BenchmarkRunRecord] = {}
        for arm, measurement in arms:
            initial_fingerprint = self._restore(dataset_snapshot)
            record = self._record(
                pair_id,
                arm,
                arm_order,
                dataset_snapshot,
                initial_fingerprint,
                environment_fingerprint,
                hardware_manifest,
                measurement(),
            )
            self._result_store.persist(record)
            records[arm] = record
        baseline_record = records[BenchmarkArm.BASELINE]
        candidate_record = records[BenchmarkArm.CANDIDATE]
        if baseline_record.initial_dataset_fingerprint != candidate_record.initial_dataset_fingerprint:
            raise ValueError("baseline and candidate must begin with matching dataset fingerprints")
        return baseline_record, candidate_record

    def _restore(self, snapshot: DatasetSnapshot) -> str:
        fingerprint = self._restorer.restore(snapshot)
        if fingerprint != snapshot.fingerprint:
            raise ValueError("restored dataset fingerprint does not match the requested snapshot")
        return fingerprint

    @staticmethod
    def _record(
        pair_id: str,
        arm: BenchmarkArm,
        arm_order: BenchmarkArmOrder,
        snapshot: DatasetSnapshot,
        initial_dataset_fingerprint: str,
        environment_fingerprint: EnvironmentFingerprint,
        hardware_manifest: HardwareManifest,
        metrics: MetricSnapshot,
    ) -> BenchmarkRunRecord:
        return BenchmarkRunRecord(
            pair_id=pair_id,
            arm=arm,
            arm_order=arm_order,
            seed=snapshot.seed,
            dataset_fingerprint=snapshot.fingerprint,
            initial_dataset_fingerprint=initial_dataset_fingerprint,
            environment_fingerprint=environment_fingerprint,
            hardware_manifest=hardware_manifest,
            metrics=metrics,
        )
