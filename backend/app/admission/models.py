"""Typed inputs and evidence-rich outputs for statistical admission."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


class AdmissionStatus(str, Enum):
    ADMITTED = "ADMITTED"
    REJECTED_SAFETY_INVARIANT = "REJECTED_SAFETY_INVARIANT"
    REJECTED_REGRESSION = "REJECTED_REGRESSION"
    REJECTED_NO_MEANINGFUL_BENEFIT = "REJECTED_NO_MEANINGFUL_BENEFIT"
    INCONCLUSIVE_NOISE = "INCONCLUSIVE_NOISE"
    INCONCLUSIVE_ENVIRONMENT = "INCONCLUSIVE_ENVIRONMENT"
    INCONCLUSIVE_MISSING_METRIC = "INCONCLUSIVE_MISSING_METRIC"


class MetricDirection(str, Enum):
    LOWER_IS_BETTER = "LOWER_IS_BETTER"
    HIGHER_IS_BETTER = "HIGHER_IS_BETTER"
    ZERO_TOLERANCE = "ZERO_TOLERANCE"


class ComparisonMode(str, Enum):
    LOG_RATIO = "LOG_RATIO"
    ABSOLUTE_DELTA = "ABSOLUTE_DELTA"
    BOOLEAN_INVARIANT = "BOOLEAN_INVARIANT"


class BenchmarkProfile(str, Enum):
    SMOKE = "SMOKE"
    AUTONOMOUS = "AUTONOMOUS"
    PUBLICATION = "PUBLICATION"


@dataclass(frozen=True)
class ProfileSettings:
    production_eligible: bool
    warmup_seconds: int
    measurement_seconds: int
    bootstrap_samples: int
    confidence: float
    candidate_pairs: int | None = None
    pilot_aa_pairs: int | None = None
    minimum_candidate_pairs: int | None = None
    maximum_candidate_pairs: int | None = None


@dataclass(frozen=True)
class MetricPolicy:
    metric_key: str
    direction: MetricDirection
    comparison_mode: ComparisonMode
    relative_cap: float | None = None
    absolute_cap: float | None = None
    hard_upper_boundary: float | None = None
    headroom_fraction: float | None = None
    minimum_benefit: float = 0.05


@dataclass(frozen=True)
class MetricEvaluationInput:
    metric_key: str
    scope_type: str
    scope_id: str
    policy: MetricPolicy
    baseline_values: tuple[float, ...]
    candidate_values: tuple[float, ...]
    required: bool = True
    applicable: bool = True
    aa_scores: tuple[float, ...] = ()


@dataclass(frozen=True)
class MetricResult:
    metric_key: str
    scope_type: str
    scope_id: str
    direction: MetricDirection
    comparison_mode: ComparisonMode
    baseline_reference: float
    allowed_regression_original_units: float
    allowed_regression_transformed: float
    pair_count: int
    bootstrap_sample_count: int
    confidence_level: float
    point_estimate_transformed: float
    upper_confidence_bound: float
    lower_confidence_bound: float
    passed: bool
    failure_reason: str | None = None
    minimum_meaningful_improvement: float | None = None
    transformed_minimum_benefit: float | None = None
    primary_benefit_lower_ci: float | None = None
    benefit_passed: bool | None = None


@dataclass(frozen=True)
class AdmissionRequest:
    candidate_id: str
    evaluation_run_id: str
    profile: BenchmarkProfile
    primary_metric_key: str
    metrics: tuple[MetricEvaluationInput, ...]
    environment_valid: bool = True
    safety_invariants_safe: bool = True
    safety_invariant_results: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdmissionResult:
    candidate_id: str
    evaluation_run_id: str
    profile: BenchmarkProfile
    primary_metric_key: str
    required_pair_count: int
    actual_pair_count: int
    status: AdmissionStatus
    reason_codes: tuple[str, ...]
    protected_metric_results: tuple[MetricResult, ...] = field(default_factory=tuple)
    primary_benefit_result: MetricResult | None = None
    safety_invariant_results: tuple[str, ...] = field(default_factory=tuple)
    production_eligible: bool = False
    family_wise_passed: bool | None = None
    family_wise_upper_bound: float | None = None


def as_tuple(values: Sequence[float]) -> tuple[float, ...]:
    """Copy values from caller-owned sequence into immutable evaluation input."""
    return tuple(values)
