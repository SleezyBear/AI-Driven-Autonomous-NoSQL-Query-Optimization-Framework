"""Paired benchmark execution with equivalent initial dataset state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from app.metrics.collector import MetricSnapshot
from app.workloads.snapshots import EnvironmentFingerprint
from benchmarks.commercebench import DatasetSnapshot


class BenchmarkArm(str, Enum):
    """The two arms of a controlled candidate comparison."""

    BASELINE = "baseline"
    CANDIDATE = "candidate"


@dataclass(frozen=True)
class BenchmarkRunRecord:
    """The persisted evidence for one arm of a paired benchmark comparison."""

    pair_id: str
    arm: BenchmarkArm
    seed: int
    dataset_fingerprint: str
    initial_dataset_fingerprint: str
    environment_fingerprint: EnvironmentFingerprint
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

    def __init__(self, restorer: SnapshotRestorer, result_store: BenchmarkResultStore) -> None:
        self._restorer = restorer
        self._result_store = result_store

    def compare(
        self,
        pair_id: str,
        dataset_snapshot: DatasetSnapshot,
        environment_fingerprint: EnvironmentFingerprint,
        baseline: Callable[[], MetricSnapshot],
        candidate: Callable[[], MetricSnapshot],
    ) -> tuple[BenchmarkRunRecord, BenchmarkRunRecord]:
        """Restore → baseline → restore → candidate and persist both measurement arms."""
        baseline_initial_fingerprint = self._restore(dataset_snapshot)
        baseline_record = self._record(
            pair_id, BenchmarkArm.BASELINE, dataset_snapshot, baseline_initial_fingerprint, environment_fingerprint, baseline()
        )
        self._result_store.persist(baseline_record)

        candidate_initial_fingerprint = self._restore(dataset_snapshot)
        candidate_record = self._record(
            pair_id, BenchmarkArm.CANDIDATE, dataset_snapshot, candidate_initial_fingerprint, environment_fingerprint, candidate()
        )
        if baseline_initial_fingerprint != candidate_initial_fingerprint:
            raise ValueError("baseline and candidate must begin with matching dataset fingerprints")
        self._result_store.persist(candidate_record)
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
        snapshot: DatasetSnapshot,
        initial_dataset_fingerprint: str,
        environment_fingerprint: EnvironmentFingerprint,
        metrics: MetricSnapshot,
    ) -> BenchmarkRunRecord:
        return BenchmarkRunRecord(
            pair_id=pair_id,
            arm=arm,
            seed=snapshot.seed,
            dataset_fingerprint=snapshot.fingerprint,
            initial_dataset_fingerprint=initial_dataset_fingerprint,
            environment_fingerprint=environment_fingerprint,
            metrics=metrics,
        )
