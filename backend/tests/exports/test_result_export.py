"""Phase 52 acceptance tests for the fixed reproducibility export layout."""

from __future__ import annotations

import csv
import json

import pytest

from app.admission.models import AdmissionResult, AdmissionStatus, BenchmarkProfile
from app.ledger.chain import AppendOnlyLedger
from app.metrics.collector import MetricSnapshot
from app.workloads.snapshots import EnvironmentFingerprint
from benchmarks.export import ExperimentExport, ResultExporter
from benchmarks.hardware import HardwareManifest
from benchmarks.runner import BenchmarkArm, BenchmarkArmOrder, BenchmarkRunRecord


def test_export_writes_the_complete_portable_result_directory(tmp_path: object) -> None:
    exporter = ResultExporter(tmp_path / "artifacts")
    exported = exporter.export(_export())

    assert {path.name for path in exported.iterdir()} == {
        "manifest.json", "environment.json", "workload.json", "policy.json", "raw_trials.csv",
        "metric_summary.csv", "admission_results.csv", "candidate_results.csv", "ai_results.jsonl",
        "ledger.jsonl", "README.md",
    }
    assert json.loads((exported / "manifest.json").read_text()) == {"experiment_id": "demo-001"}
    with (exported / "raw_trials.csv").open() as raw_trials:
        row = next(csv.DictReader(raw_trials))
    assert row["arm"] == "baseline"
    assert json.loads(row["hardware_manifest"])["architecture"] == "x86_64"
    with (exported / "admission_results.csv").open() as admissions:
        admission = next(csv.DictReader(admissions))
    assert admission["status"] == "ADMITTED"
    assert json.loads((exported / "ai_results.jsonl").read_text()) == {"candidate_id": "candidate-1"}
    assert "complete, read-only result export" in (exported / "README.md").read_text()


def test_export_rejects_path_traversal_and_existing_evidence(tmp_path: object) -> None:
    exporter = ResultExporter(tmp_path / "artifacts")
    invalid = _export(experiment_id="../outside")
    with pytest.raises(ValueError, match="safe relative"):
        exporter.export(invalid)
    exporter.export(_export())
    with pytest.raises(FileExistsError, match="already exist"):
        exporter.export(_export())


def _export(experiment_id: str = "demo-001") -> ExperimentExport:
    ledger = AppendOnlyLedger()
    ledger.append({"index": "before"}, {"index": "intended"}, {"index": "after"}, {"type": "CREATE_INDEX"}, {"type": "DROP_INDEX"}, "evidence", "worker")
    trial = BenchmarkRunRecord(
        pair_id="pair-1",
        arm=BenchmarkArm.BASELINE,
        arm_order=BenchmarkArmOrder.AB,
        seed=42,
        dataset_fingerprint="dataset",
        initial_dataset_fingerprint="dataset",
        environment_fingerprint=EnvironmentFingerprint.from_mapping({"mongo": "8.0"}),
        hardware_manifest=_manifest(),
        metrics=MetricSnapshot(1, 2, 3, 4, 5, 6, None, None, None, None, None, None, 7, 8, 9, 10, 0, 0),
    )
    admission = AdmissionResult("candidate-1", "run-1", BenchmarkProfile.SMOKE, "p95_latency_ms", 1, 1, AdmissionStatus.ADMITTED, ())
    return ExperimentExport(
        experiment_id,
        {"experiment_id": experiment_id},
        {"docker": "29.6.1"},
        {"profile": "smoke"},
        {"primary_metric": "p95_latency_ms"},
        (trial,),
        ({"metric_key": "p95_latency_ms", "candidate": 2.0},),
        (admission,),
        ({"candidate_id": "candidate-1", "result": "ADMITTED"},),
        ({"candidate_id": "candidate-1"},),
        ledger.entries,
    )


def _manifest() -> HardwareManifest:
    return HardwareManifest("15.7.7", "Intel", "x86_64", 6, 12, 16, "29.6.1", 12, 16, "8.0", "17", "3.10", "1.26", "1.12", "4.13", "0.32", "chat", "embed")
