"""Authoritative R28 execution: single-pair and PUBLICATION sampling runs.

This module wires the frozen ablation matrix and the frozen PUBLICATION
sampling protocol into the accepted benchmark executor and admission
statistics.  It is the only place that schedules A/A calibration pairs,
candidate pairs, and the admission gate.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from benchmarks.ablations import AblationPlan, candidate_setup_for, resolve_plan
from benchmarks.commercebench import CommerceBench, WorkloadProfile
from benchmarks.commercebench.validation import validate_materialized, validate_snapshot
from benchmarks.mongodb_executor import (
    BenchmarkExecutionSettings,
    JsonTrialResultStore,
    RealMongoBenchmarkExecutor,
)
from benchmarks.publication import SamplingStatus, publication_protocol, required_candidate_pairs
from benchmarks.runner import BenchmarkArmOrder

from app.ablations.experiments import AblationMode
from app.admission.models import (
    AdmissionRequest,
    AdmissionResult,
    BenchmarkProfile,
    ComparisonMode,
    MetricDirection,
    MetricEvaluationInput,
)
from app.admission.policy import DEFAULT_POLICIES
from app.admission.statistics import deterministic_arm_order, evaluate_candidate_admission, transform_regression

PROFILE_OPERATION_DEFAULTS: dict[str, tuple[int, int]] = {"smoke": (10, 50), "standard": (30, 200)}
PRIMARY_METRIC_KEY = "p99_latency_ms"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git_provenance(root: Path) -> dict[str, str]:
    """Best-effort git revision and dirty state for durable experiment manifests."""
    def _run(*args: str) -> str:
        completed = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
        return completed.stdout.strip() if completed.returncode == 0 else ""

    return {"revision": _run("rev-parse", "HEAD"), "dirty": _run("status", "--porcelain") or "clean"}


def build_settings(
    profile: WorkloadProfile,
    *,
    warmup_operations: int | None = None,
    measurement_operations: int | None = None,
    warmup_seconds: float | None = None,
    measurement_seconds: float | None = None,
) -> BenchmarkExecutionSettings:
    """Build executor settings, using the frozen time-based PUBLICATION profile.

    PUBLICATION windows are always seconds and may not be overridden; any
    attempt to pass operation counts for PUBLICATION is rejected.
    """
    if profile is WorkloadProfile.PUBLICATION:
        if warmup_operations is not None or measurement_operations is not None:
            raise ValueError("PUBLICATION measurement is time-based; operation counts are not valid")
        protocol = publication_protocol()
        resolved_warmup = protocol.warmup_seconds if warmup_seconds is None else warmup_seconds
        resolved_measurement = protocol.measurement_seconds if measurement_seconds is None else measurement_seconds
        if resolved_warmup != protocol.warmup_seconds or resolved_measurement != protocol.measurement_seconds:
            raise ValueError("PUBLICATION warmup/measurement windows are frozen and may not be overridden")
        return BenchmarkExecutionSettings(
            warmup_operations=None,
            measurement_operations=None,
            warmup_seconds=float(resolved_warmup),
            measurement_seconds=float(resolved_measurement),
        )
    default_warmup, default_measurement = PROFILE_OPERATION_DEFAULTS[profile.value]
    if warmup_seconds is not None or measurement_seconds is not None:
        return BenchmarkExecutionSettings(
            warmup_operations=None,
            measurement_operations=None,
            warmup_seconds=float(warmup_seconds if warmup_seconds is not None else default_warmup),
            measurement_seconds=float(measurement_seconds if measurement_seconds is not None else default_measurement),
        )
    return BenchmarkExecutionSettings(
        warmup_operations=default_warmup if warmup_operations is None else warmup_operations,
        measurement_operations=default_measurement if measurement_operations is None else measurement_operations,
    )


def aa_pair_ids(prefix: str) -> tuple[str, ...]:
    """Exactly the frozen 12 A/A calibration pair identifiers."""
    protocol = publication_protocol()
    return tuple(f"{prefix}-aa-{index:02d}" for index in range(1, protocol.aa_pairs + 1))


def candidate_pair_ids(prefix: str, count: int) -> tuple[str, ...]:
    """Candidate pair identifiers, enforcing the frozen 15-40 range."""
    protocol = publication_protocol()
    if not protocol.minimum_candidate_pairs <= count <= protocol.maximum_candidate_pairs:
        raise ValueError(f"candidate pair count {count} is outside the frozen {protocol.minimum_candidate_pairs}-{protocol.maximum_candidate_pairs} range")
    return tuple(f"{prefix}-cand-{index:02d}" for index in range(1, count + 1))


def _jsonable(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {field: _jsonable(getattr(value, field)) for field in value.__dataclass_fields__}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def write_json(path: Path, payload: object) -> None:
    """Atomically write JSON so interrupted runs never leave partial evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def llm_ranker(provider: Any) -> Callable[[tuple[Any, ...]], tuple[str, ...]]:
    """Build the accepted LLM-assisted ranking boundary as a sync callable."""
    from app.ai.provider import RankingCandidateInput

    def _rank(candidates: tuple[Any, ...]) -> tuple[str, ...]:
        inputs = tuple(RankingCandidateInput(handle=candidate.label, safe_summary=candidate.safe_summary) for candidate in candidates)
        ranking = asyncio.run(provider.rank_candidate_handles(inputs))
        handles: tuple[str, ...] = tuple(str(handle) for handle in ranking.candidate_handles)
        return handles

    return _rank


def experience_prioritizer() -> Callable[[tuple[str, ...]], tuple[str, ...]]:
    """Build the accepted experience-memory prioritization boundary."""
    from app.experience.memory import ExperienceMemory, InMemoryExperienceRepository

    memory = ExperienceMemory(InMemoryExperienceRepository())

    def _prioritize(order: tuple[str, ...]) -> tuple[str, ...]:
        # Retrieval is invoked even when no precedent exists; the ordering is
        # never fabricated and the pure memory contract is preserved.
        prioritized: tuple[str, ...] = memory.prioritize(order, embedding=tuple(0.0 for _ in range(768)), enabled=True)
        return prioritized

    return _prioritize


def plan_for_mode(mode: AblationMode) -> AblationPlan:
    """Resolve the executable plan for a mode, consulting real boundaries when needed."""
    from benchmarks.ablations import configuration_for as _configuration_for

    configuration = _configuration_for(mode)
    ranker = None
    prioritize = None
    if configuration.llm_ranking:
        from app.ai.provider import OllamaAIProvider

        import httpx

        provider = OllamaAIProvider(
            client=httpx.AsyncClient(base_url="http://localhost:11434", timeout=600.0),
            model="gemma4:e4b",
            embedding_model="embeddinggemma",
        )
        ranker = llm_ranker(provider)
    if configuration.experience_memory:
        prioritize = experience_prioritizer()
    return resolve_plan(mode, ranker=ranker, prioritize=prioritize)


def _arm_order(pair_id: str, pair_number: int) -> BenchmarkArmOrder:
    return BenchmarkArmOrder[deterministic_arm_order(pair_id, pair_number)]


def run_single_pair(
    profile: WorkloadProfile,
    mode: AblationMode,
    uri: str,
    output: Path,
    *,
    pair_id: str,
    settings: BenchmarkExecutionSettings | None = None,
) -> dict[str, object]:
    """Run one AB/BA ablation pair for SMOKE or STANDARD and persist evidence."""
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing evidence: {output}")
    snapshot = CommerceBench().reset(profile)
    validation = validate_snapshot(snapshot)
    resolved_settings = settings or build_settings(profile)
    executor = RealMongoBenchmarkExecutor(uri, settings=resolved_settings)
    observed = executor.materialize_and_count(snapshot)
    validate_materialized(validation, observed)
    plan = plan_for_mode(mode)
    baseline, candidate = executor.run_pair(
        pair_id, snapshot, JsonTrialResultStore(output), _arm_order(pair_id, 1), candidate_setup=candidate_setup_for(plan)
    )
    metadata: dict[str, object] = {
        "experiment_id": pair_id,
        "profile": profile.value,
        "mode": mode.value,
        "dataset": validation.to_manifest(),
        "observed_at_materialization": observed,
        "plan": _plan_manifest(plan),
        "measurement": {
            "unit": "seconds" if resolved_settings.duration_based else "operations",
            "warmup": resolved_settings.warmup_seconds if resolved_settings.duration_based else resolved_settings.warmup_operations,
            "measurement": resolved_settings.measurement_seconds if resolved_settings.duration_based else resolved_settings.measurement_operations,
        },
        "reset": executor.reset_timing_summary(),
        "environment": executor.environment_fingerprint(),
        "provenance": git_provenance(Path(__file__).resolve().parents[1]),
        "created_at": utc_now(),
        "arm_order": baseline.arm_order.value,
    }
    write_json(output.with_suffix(".manifest.json"), metadata)
    return metadata


def _plan_manifest(plan: AblationPlan) -> dict[str, object]:
    selected = plan.selected_index
    return {
        "mode": plan.mode.value,
        "deterministic_candidates": plan.deterministic_candidates,
        "llm_ranking": plan.llm_ranking,
        "safety_gate": plan.safety_gate,
        "experience_memory": plan.experience_memory,
        "sandbox_only": plan.sandbox_only,
        "candidates": [asdict(candidate) for candidate in plan.candidates],
        "ranking_order": list(plan.ranking_order),
        "experience_invoked": plan.experience_invoked,
        "selected_index": asdict(selected) if selected is not None else None,
    }


def run_publication(profile: WorkloadProfile, mode: AblationMode, uri: str, output_dir: Path, *, prefix: str) -> dict[str, object]:
    """Run the frozen PUBLICATION sampling protocol for one ablation mode.

    Schedules exactly 12 A/A calibration pairs, then the required candidate
    pairs (15-40) derived from the accepted required-N implementation, then
    the frozen admission gate.  Resumable per pair: existing pair evidence is
    never re-run or overwritten.
    """
    protocol = publication_protocol()
    protocol.assert_frozen()
    output_dir = Path(output_dir)
    pairs_dir = output_dir / "pairs"
    pairs_dir.mkdir(parents=True, exist_ok=True)
    snapshot = CommerceBench().reset(profile)
    validation = validate_snapshot(snapshot)
    settings = build_settings(profile)
    executor = RealMongoBenchmarkExecutor(uri, settings=settings)
    observed = executor.materialize_and_count(snapshot)
    validate_materialized(validation, observed)
    plan = plan_for_mode(mode)
    environment = executor.environment_fingerprint()
    provenance = git_provenance(Path(__file__).resolve().parents[1])
    write_json(output_dir / "dataset.json", validation.to_manifest())
    write_json(output_dir / "plan.json", _plan_manifest(plan))
    write_json(
        output_dir / "reset.json",
        {
            "reset_implementation": executor.reset_timing_summary()["reset_implementation"],
            "reset_version": "delta-reset-v1",
            "environment": environment,
            "provenance": provenance,
        },
    )

    aa_paths = [
        _ensure_pair(executor, snapshot, pairs_dir, pair_id, number, candidate_setup=None)
        for number, pair_id in enumerate(aa_pair_ids(prefix), start=1)
    ]
    aa_values = tuple(_pair_p99(path) for path in aa_paths)
    aa_scores = tuple(
        transform_regression(baseline, candidate, MetricDirection.LOWER_IS_BETTER, ComparisonMode.LOG_RATIO)
        for baseline, candidate in aa_values
    )
    aa_baselines = tuple(baseline for baseline, _ in aa_values)
    policy = DEFAULT_POLICIES[PRIMARY_METRIC_KEY]
    required = required_candidate_pairs(
        aa_scores=aa_scores,
        baseline_values=aa_baselines,
        policy=policy,
        primary_direction=MetricDirection.LOWER_IS_BETTER,
        minimum_benefit=policy.minimum_benefit,
        minimum_pairs=protocol.minimum_candidate_pairs,
        maximum_pairs=protocol.maximum_candidate_pairs,
    )
    summary: dict[str, object] = {
        "experiment_id": prefix,
        "profile": profile.value,
        "mode": mode.value,
        "protocol": asdict(protocol),
        "aa_pair_count": len(aa_paths),
        "required_pairs": required.required_pairs,
        "sampling_status": required.status.value,
        "dataset": validation.to_manifest(),
        "plan": _plan_manifest(plan),
        "reset_implementation": executor.reset_timing_summary()["reset_implementation"],
        "reset_timings": executor.reset_timing_summary(),
        "environment": environment,
        "provenance": provenance,
        "created_at": utc_now(),
    }
    write_json(output_dir / "progress.json", {"phase": "candidate_sampling", "aa_pairs": len(aa_paths), "required_pairs": required.required_pairs})
    if required.status is SamplingStatus.INCONCLUSIVE_NOISE:
        summary["admission"] = {"status": "INCONCLUSIVE_NOISE", "reason_codes": ["AA_CALIBRATION_EXCEEDS_PROFILE_MAXIMUM"]}
        write_json(output_dir / "summary.json", summary)
        return summary

    setup = candidate_setup_for(plan)
    candidate_paths = [
        _ensure_pair(executor, snapshot, pairs_dir, pair_id, number, candidate_setup=setup)
        for number, pair_id in enumerate(candidate_pair_ids(prefix, required.required_pairs), start=1)
    ]
    candidate_pairs = tuple(_pair_p99(path) for path in candidate_paths)
    baseline_values = tuple(baseline for baseline, _ in candidate_pairs)
    candidate_values = tuple(candidate for _, candidate in candidate_pairs)
    metric = MetricEvaluationInput(
        metric_key=PRIMARY_METRIC_KEY,
        scope_type="GLOBAL",
        scope_id="all",
        policy=policy,
        baseline_values=baseline_values,
        candidate_values=candidate_values,
        aa_scores=aa_scores,
    )
    selected = plan.selected_index
    request = AdmissionRequest(
        candidate_id=selected.name if selected is not None else "native",
        evaluation_run_id=prefix,
        profile=BenchmarkProfile.PUBLICATION,
        primary_metric_key=PRIMARY_METRIC_KEY,
        metrics=(metric,),
        environment_valid=True,
        safety_invariants_safe=True,
    )
    admission = evaluate_candidate_admission(request)
    summary["candidate_pair_count"] = len(candidate_paths)
    summary["admission"] = _serialize_admission(admission)
    summary["gate_enabled"] = plan.safety_gate
    summary["sandbox_only"] = plan.sandbox_only
    write_json(output_dir / "admission.json", _serialize_admission(admission))
    write_json(output_dir / "summary.json", summary)
    return summary


def _ensure_pair(
    executor: RealMongoBenchmarkExecutor,
    snapshot: Any,
    pairs_dir: Path,
    pair_id: str,
    pair_number: int,
    *,
    candidate_setup: Callable[[Any], None] | None,
) -> Path:
    """Return existing pair evidence, or run and persist the pair exactly once."""
    path = pairs_dir / f"{pair_id}.jsonl"
    if path.exists() and path.stat().st_size > 0:
        return path
    executor.run_pair(pair_id, snapshot, JsonTrialResultStore(path), _arm_order(pair_id, pair_number), candidate_setup=candidate_setup)
    return path


def _pair_p99(path: Path) -> tuple[float, float]:
    """Extract (baseline_p99, candidate_p99) from persisted one-record-per-line evidence."""
    baseline: float | None = None
    candidate: float | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        value = record.get("measurement", {}).get("p99_latency_ms")
        if value is None:
            raise RuntimeError(f"{path} recorded an arm with no successful operations")
        if record.get("arm") == "baseline":
            baseline = float(value)
        elif record.get("arm") == "candidate":
            candidate = float(value)
    if baseline is None or candidate is None:
        raise RuntimeError(f"{path} is missing a baseline or candidate arm")
    return baseline, candidate


def _serialize_admission(result: AdmissionResult) -> dict[str, object]:
    return {
        "candidate_id": result.candidate_id,
        "evaluation_run_id": result.evaluation_run_id,
        "profile": result.profile.value,
        "primary_metric_key": result.primary_metric_key,
        "required_pair_count": result.required_pair_count,
        "actual_pair_count": result.actual_pair_count,
        "status": result.status.value,
        "reason_codes": list(result.reason_codes),
        "production_eligible": result.production_eligible,
        "family_wise_passed": result.family_wise_passed,
        "family_wise_upper_bound": result.family_wise_upper_bound,
        "protected_metric_results": [_jsonable(item) for item in result.protected_metric_results],
        "primary_benefit_result": _jsonable(result.primary_benefit_result) if result.primary_benefit_result is not None else None,
        "safety_invariant_results": list(result.safety_invariant_results),
    }
