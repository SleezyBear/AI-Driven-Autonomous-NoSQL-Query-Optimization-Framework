"""Portable, evidence-preserving experiment result exports."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

from app.admission.models import AdmissionResult
from app.ledger.chain import LedgerEntry
from benchmarks.runner import BenchmarkRunRecord


_EXPERIMENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_REQUIRED_FILES = (
    "manifest.json",
    "environment.json",
    "workload.json",
    "policy.json",
    "raw_trials.csv",
    "metric_summary.csv",
    "admission_results.csv",
    "candidate_results.csv",
    "ai_results.jsonl",
    "ledger.jsonl",
    "README.md",
)


@dataclass(frozen=True)
class ExperimentExport:
    """All evidence required to export a single reproducible experiment."""

    experiment_id: str
    manifest: Mapping[str, object]
    environment: Mapping[str, object]
    workload: Mapping[str, object]
    policy: Mapping[str, object]
    raw_trials: tuple[BenchmarkRunRecord, ...]
    metric_summary: tuple[Mapping[str, object], ...]
    admission_results: tuple[AdmissionResult, ...]
    candidate_results: tuple[Mapping[str, object], ...]
    ai_results: tuple[Mapping[str, object], ...]
    ledger_entries: tuple[LedgerEntry, ...]


class ResultExporter:
    """Write the fixed Phase 52 artifact layout without overwriting evidence."""

    def __init__(self, artifacts_root: Path = Path("artifacts")) -> None:
        self._artifacts_root = artifacts_root

    def export(self, evidence: ExperimentExport) -> Path:
        """Create one complete artifact directory and return its path."""
        if not _EXPERIMENT_ID.fullmatch(evidence.experiment_id):
            raise ValueError("experiment ID must be a safe relative artifact name")
        directory = self._artifacts_root / evidence.experiment_id
        if directory.exists():
            raise FileExistsError(f"experiment artifacts already exist: {directory}")
        directory.mkdir(parents=True)
        self._write_json(directory / "manifest.json", evidence.manifest)
        self._write_json(directory / "environment.json", evidence.environment)
        self._write_json(directory / "workload.json", evidence.workload)
        self._write_json(directory / "policy.json", evidence.policy)
        self._write_csv(directory / "raw_trials.csv", tuple(self._trial_row(record) for record in evidence.raw_trials))
        self._write_csv(directory / "metric_summary.csv", evidence.metric_summary)
        self._write_csv(
            directory / "admission_results.csv",
            tuple(self._admission_row(result) for result in evidence.admission_results),
        )
        self._write_csv(directory / "candidate_results.csv", evidence.candidate_results)
        self._write_jsonl(directory / "ai_results.jsonl", evidence.ai_results)
        self._write_jsonl(directory / "ledger.jsonl", evidence.ledger_entries)
        (directory / "README.md").write_text(self._readme(evidence.experiment_id), encoding="utf-8")
        if {path.name for path in directory.iterdir()} != set(_REQUIRED_FILES):
            raise RuntimeError("result export is incomplete")
        return directory

    @staticmethod
    def _trial_row(record: BenchmarkRunRecord) -> Mapping[str, object]:
        row: dict[str, object] = {
            "pair_id": record.pair_id,
            "arm": record.arm.value,
            "arm_order": record.arm_order.value,
            "seed": record.seed,
            "dataset_fingerprint": record.dataset_fingerprint,
            "initial_dataset_fingerprint": record.initial_dataset_fingerprint,
            "environment_fingerprint": dict(record.environment_fingerprint.facts),
            "hardware_manifest": record.hardware_manifest,
        }
        row.update(asdict(record.metrics))
        return row

    @staticmethod
    def _admission_row(result: AdmissionResult) -> Mapping[str, object]:
        return {
            "candidate_id": result.candidate_id,
            "evaluation_run_id": result.evaluation_run_id,
            "profile": result.profile.value,
            "primary_metric_key": result.primary_metric_key,
            "required_pair_count": result.required_pair_count,
            "actual_pair_count": result.actual_pair_count,
            "status": result.status.value,
            "reason_codes": result.reason_codes,
            "production_eligible": result.production_eligible,
            "protected_metric_results": result.protected_metric_results,
            "primary_benefit_result": result.primary_benefit_result,
            "safety_invariant_results": result.safety_invariant_results,
        }

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.write_text(json.dumps(_json_value(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def _write_jsonl(path: Path, values: Sequence[object]) -> None:
        path.write_text(
            "".join(json.dumps(_json_value(value), sort_keys=True) + "\n" for value in values),
            encoding="utf-8",
        )

    @staticmethod
    def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
        headers = tuple(sorted({key for row in rows for key in row}))
        with path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _csv_value(row.get(key)) for key in headers})

    @staticmethod
    def _readme(experiment_id: str) -> str:
        return (
            f"# Experiment {experiment_id}\n\n"
            "This directory is a complete, read-only result export. `manifest.json` identifies the "
            "export; `environment.json`, `workload.json`, and `policy.json` preserve its inputs. "
            "CSV files contain raw trials, metric summaries, admissions, and candidates. JSONL files "
            "preserve AI and append-only ledger evidence.\n"
        )


def _csv_value(value: object) -> object:
    return json.dumps(_json_value(value), sort_keys=True) if isinstance(value, (dict, list, tuple)) or is_dataclass(value) else value


def _json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value
