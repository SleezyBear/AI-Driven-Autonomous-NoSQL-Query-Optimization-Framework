"""R28: executor window units and true one-record-per-line JSONL evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.metrics.collector import CounterDeltas
from benchmarks.mongodb_executor import (
    BenchmarkExecutionSettings,
    JsonTrialResultStore,
    RealBenchmarkMeasurement,
    RealBenchmarkRunRecord,
    _window_open,
)
from benchmarks.runner import BenchmarkArm, BenchmarkArmOrder


def test_duration_settings_and_count_settings_are_mutually_exclusive() -> None:
    duration = BenchmarkExecutionSettings(warmup_operations=None, measurement_operations=None, warmup_seconds=60, measurement_seconds=120)
    assert duration.duration_based is True
    counts = BenchmarkExecutionSettings(warmup_operations=60, measurement_operations=120)
    assert counts.duration_based is False
    with pytest.raises(ValueError, match="not both"):
        BenchmarkExecutionSettings(warmup_operations=60, measurement_operations=120, warmup_seconds=60, measurement_seconds=120)
    with pytest.raises(ValueError, match="both warmup_seconds and measurement_seconds"):
        BenchmarkExecutionSettings(warmup_operations=None, measurement_operations=None, warmup_seconds=60)
    with pytest.raises(ValueError, match="positive"):
        BenchmarkExecutionSettings(warmup_operations=None, measurement_operations=None, warmup_seconds=0, measurement_seconds=0)


def test_window_open_predicate_uses_only_one_unit() -> None:
    assert _window_open(None, 1) is True
    assert _window_open(None, 0) is False
    assert _window_open(10_000_000_000.0, None) is True
    assert _window_open(0.0, None) is False


def _record() -> RealBenchmarkRunRecord:
    measurement = RealBenchmarkMeasurement(10, 0, 0, 1.0, 10.0, 1.0, 2.0, 3.0, CounterDeltas(0.0, 0.0, 0.0, 0.0, 0.0))
    return RealBenchmarkRunRecord(
        pair_id="pair-1",
        arm=BenchmarkArm.BASELINE,
        arm_order=BenchmarkArmOrder.AB,
        seed=42,
        generator_version="2",
        dataset_fingerprint="abc",
        initial_dataset_fingerprint="abc",
        environment={"mongodb_version": "8.0.0"},
        measurement=measurement,
    )


def test_evidence_is_true_jsonl_not_a_json_array(tmp_path: Path) -> None:
    path = tmp_path / "evidence.jsonl"
    JsonTrialResultStore(path).persist((_record(), _record()))
    text = path.read_text(encoding="utf-8")
    assert not text.lstrip().startswith("[")
    lines = [line for line in text.splitlines() if line]
    assert len(lines) == 2
    for line in lines:
        assert json.loads(line)["pair_id"] == "pair-1"


def test_append_mode_preserves_individual_pair_evidence(tmp_path: Path) -> None:
    path = tmp_path / "pairs.jsonl"
    JsonTrialResultStore(path, append=True).persist((_record(),))
    JsonTrialResultStore(path, append=True).persist((_record(),))
    assert len([line for line in path.read_text(encoding="utf-8").splitlines() if line]) == 2
