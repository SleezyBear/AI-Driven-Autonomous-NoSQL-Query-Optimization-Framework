"""Exact deterministic paired-bootstrap non-regression methodology."""

from __future__ import annotations

import hashlib
import math
from typing import Any, Iterable, cast

import numpy as np

from app.admission.models import (
    AdmissionRequest,
    AdmissionResult,
    AdmissionStatus,
    BenchmarkProfile,
    ComparisonMode,
    MetricDirection,
    MetricEvaluationInput,
    MetricPolicy,
    MetricResult,
)
from app.admission.policy import PROFILES

EPSILON = 1e-12
ONE_SIDED_Z_95 = 1.645
ZERO_REGRESSION_SENTINEL = 1_000_000_000.0
MINIMUM_OBSERVATIONS = 3


def transform_regression(baseline: float, candidate: float, direction: MetricDirection, mode: ComparisonMode) -> float:
    """Return a score where positive is always a regression and negative an improvement."""
    _validate_value(baseline)
    _validate_value(candidate)
    if mode == ComparisonMode.BOOLEAN_INVARIANT:
        return 0.0 if baseline == candidate else 1.0
    if mode == ComparisonMode.ABSOLUTE_DELTA:
        return candidate - baseline if direction == MetricDirection.LOWER_IS_BETTER else baseline - candidate
    if baseline == 0 and candidate == 0:
        return 0.0
    if baseline == 0:
        return ZERO_REGRESSION_SENTINEL if direction == MetricDirection.LOWER_IS_BETTER else -ZERO_REGRESSION_SENTINEL
    if candidate == 0:
        return -ZERO_REGRESSION_SENTINEL if direction == MetricDirection.LOWER_IS_BETTER else ZERO_REGRESSION_SENTINEL
    ratio = candidate / baseline if direction == MetricDirection.LOWER_IS_BETTER else baseline / candidate
    return math.log(ratio)


def transform_benefit(baseline: float, candidate: float, direction: MetricDirection) -> float:
    """Return positive log-space benefit for a declared primary objective."""
    _validate_value(baseline)
    _validate_value(candidate)
    if baseline == candidate == 0:
        return 0.0
    if baseline == 0:
        return -ZERO_REGRESSION_SENTINEL if direction == MetricDirection.LOWER_IS_BETTER else ZERO_REGRESSION_SENTINEL
    if candidate == 0:
        return ZERO_REGRESSION_SENTINEL if direction == MetricDirection.LOWER_IS_BETTER else -ZERO_REGRESSION_SENTINEL
    ratio = baseline / candidate if direction == MetricDirection.LOWER_IS_BETTER else candidate / baseline
    return math.log(ratio)


def calculate_baseline_reference(values: Iterable[float], mode: ComparisonMode) -> float:
    """Use geometric mean for log ratios and arithmetic mean for absolute deltas."""
    array = _finite_array(values)
    if len(array) == 0:
        raise ValueError("Baseline observations are required.")
    if mode == ComparisonMode.LOG_RATIO:
        if np.any(array < 0):
            raise ValueError("Log-ratio baseline reference cannot contain negative observations.")
        if np.any(array == 0):
            return 0.0
        return float(np.exp(np.mean(np.log(array))))
    return float(np.mean(array))


def calculate_allowed_regression(baseline_reference: float, policy: MetricPolicy) -> float:
    """Calculate original-unit dynamic margin; variance is intentionally absent."""
    candidates: list[float] = []
    if policy.relative_cap is not None:
        candidates.append(baseline_reference * policy.relative_cap)
    if policy.absolute_cap is not None:
        candidates.append(policy.absolute_cap)
    if policy.hard_upper_boundary is not None:
        if baseline_reference >= policy.hard_upper_boundary:
            return 0.0
        if policy.headroom_fraction is not None:
            candidates.append(policy.headroom_fraction * max(policy.hard_upper_boundary - baseline_reference, 0.0))
    if not candidates:
        raise ValueError("Protected metric policy has no regression margin.")
    return min(candidates)


def calculate_transformed_regression_margin(baseline_reference: float, allowed_delta: float, policy: MetricPolicy) -> float:
    """Map an original-unit margin into the metric's comparison domain."""
    if policy.comparison_mode == ComparisonMode.ABSOLUTE_DELTA:
        return allowed_delta
    if policy.comparison_mode != ComparisonMode.LOG_RATIO:
        return 0.0
    if baseline_reference <= 0:
        return 0.0
    if policy.direction == MetricDirection.LOWER_IS_BETTER:
        return math.log((baseline_reference + allowed_delta) / baseline_reference)
    minimum_candidate = baseline_reference - allowed_delta
    if minimum_candidate <= 0:
        raise ValueError("Higher-is-better log policy has invalid minimum candidate value.")
    return math.log(baseline_reference / minimum_candidate)


def calculate_transformed_minimum_benefit(direction: MetricDirection, minimum_benefit: float = 0.05) -> float:
    """Map the fixed minimum meaningful improvement into log-benefit space."""
    if not 0 < minimum_benefit < 1:
        raise ValueError("Minimum benefit must be in (0, 1).")
    return math.log(1 / (1 - minimum_benefit)) if direction == MetricDirection.LOWER_IS_BETTER else math.log(1 + minimum_benefit)


def estimate_required_pairs(aa_scores: Iterable[float], transformed_margin: float, maximum_pairs: int) -> int:
    """Apply the exact one-sided A/A calibration formula with sample ddof=1."""
    if transformed_margin <= EPSILON:
        return maximum_pairs
    scores = _finite_array(aa_scores)
    if len(scores) < 2:
        raise ValueError("A/A calibration requires at least two scores.")
    standard_deviation = float(np.std(scores, ddof=1))
    target_half_width = 0.5 * transformed_margin
    return int(math.ceil((ONE_SIDED_Z_95 * standard_deviation / target_half_width) ** 2))


def paired_bootstrap_ci(scores: Iterable[float], bootstrap_samples: int, seed: int, confidence: float = 0.95) -> tuple[float, float, float]:
    """Explicit deterministic paired resampling of arithmetic mean transformed scores."""
    array = _finite_array(scores)
    if len(array) == 0:
        raise ValueError("Bootstrap requires at least one finite score.")
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(array), size=(bootstrap_samples, len(array)))
    means = np.mean(array[indices], axis=1)
    lower = float(np.percentile(means, (1 - confidence) * 100))
    upper = float(np.percentile(means, confidence * 100))
    return float(np.mean(array)), lower, upper


def paired_max_statistic_upper_bound(metrics: Iterable[MetricEvaluationInput], evaluation_run_id: str, bootstrap_samples: int, confidence: float) -> float:
    """Upper bound for simultaneous non-regression across the complete metric family.

    Each resample uses the same pair indices for every protected metric.  The
    resampled maximum of ``mean(regression score) - allowed margin`` is the
    family statistic; its one-sided upper quantile must be non-positive.
    """
    family = tuple(metrics)
    if not family:
        raise ValueError("A protected metric family is required.")
    pair_count = len(family[0].baseline_values)
    if pair_count < MINIMUM_OBSERVATIONS or any(len(metric.baseline_values) != pair_count or len(metric.candidate_values) != pair_count for metric in family):
        raise ValueError("Protected metric family requires aligned minimum observations.")
    excesses: list[np.ndarray[Any, Any]] = []
    for metric in family:
        reference = calculate_baseline_reference(metric.baseline_values, metric.policy.comparison_mode)
        margin = calculate_transformed_regression_margin(reference, calculate_allowed_regression(reference, metric.policy), metric.policy)
        scores = _finite_array(transform_regression(baseline, candidate, metric.policy.direction, metric.policy.comparison_mode) for baseline, candidate in zip(metric.baseline_values, metric.candidate_values))
        excesses.append(scores - margin)
    seed = int.from_bytes(hashlib.sha256(f"{evaluation_run_id}|family-max-bootstrap".encode("utf-8")).digest()[:8], "big")
    indices = np.random.default_rng(seed).integers(0, pair_count, size=(bootstrap_samples, pair_count))
    maxima = np.max(np.stack([np.mean(scores[indices], axis=1) for scores in excesses]), axis=0)
    return float(np.percentile(maxima, confidence * 100))


def deterministic_arm_order(evaluation_run_id: str, pair_index: int) -> str:
    """Choose reproducible random-looking AB/BA ordering from SHA-256 run identity."""
    digest = hashlib.sha256(f"{evaluation_run_id}|{pair_index}".encode("utf-8")).digest()
    return "AB" if digest[0] % 2 == 0 else "BA"


def evaluate_non_regression(metric: MetricEvaluationInput, evaluation_run_id: str, bootstrap_samples: int, confidence: float) -> MetricResult:
    """Evaluate one protected metric's one-sided upper bootstrap gate."""
    baseline_reference = calculate_baseline_reference(metric.baseline_values, metric.policy.comparison_mode)
    allowed = calculate_allowed_regression(baseline_reference, metric.policy)
    margin = calculate_transformed_regression_margin(baseline_reference, allowed, metric.policy)
    scores = tuple(transform_regression(b, c, metric.policy.direction, metric.policy.comparison_mode) for b, c in zip(metric.baseline_values, metric.candidate_values))
    point, lower, upper = paired_bootstrap_ci(scores, bootstrap_samples, _bootstrap_seed(evaluation_run_id, metric))
    passed = upper <= margin + EPSILON
    return MetricResult(metric.metric_key, metric.scope_type, metric.scope_id, metric.policy.direction, metric.policy.comparison_mode, baseline_reference, allowed, margin, len(scores), bootstrap_samples, confidence, point, upper, lower, passed, None if passed else "UPPER_CI_EXCEEDS_REGRESSION_MARGIN")


def evaluate_primary_benefit(metric: MetricEvaluationInput, evaluation_run_id: str, bootstrap_samples: int, confidence: float) -> MetricResult:
    """Evaluate the declared primary metric's one-sided lower bootstrap benefit gate."""
    protected = evaluate_non_regression(metric, evaluation_run_id, bootstrap_samples, confidence)
    scores = tuple(transform_benefit(b, c, metric.policy.direction) for b, c in zip(metric.baseline_values, metric.candidate_values))
    _, lower, _ = paired_bootstrap_ci(scores, bootstrap_samples, _bootstrap_seed(evaluation_run_id, metric))
    threshold = calculate_transformed_minimum_benefit(metric.policy.direction, metric.policy.minimum_benefit)
    benefit_passed = lower + EPSILON >= threshold
    return MetricResult(**{**protected.__dict__, "lower_confidence_bound": lower, "minimum_meaningful_improvement": metric.policy.minimum_benefit, "transformed_minimum_benefit": threshold, "primary_benefit_lower_ci": lower, "benefit_passed": benefit_passed})


def evaluate_candidate_admission(request: AdmissionRequest) -> AdmissionResult:
    """Apply the frozen precedence: invariant, environment, missing, noise, regression, benefit."""
    settings = PROFILES[request.profile]
    actual_pairs = min((len(metric.baseline_values) for metric in request.metrics if metric.required and metric.applicable), default=0)
    base = dict(candidate_id=request.candidate_id, evaluation_run_id=request.evaluation_run_id, profile=request.profile, primary_metric_key=request.primary_metric_key, actual_pair_count=actual_pairs, production_eligible=settings.production_eligible)
    if not request.safety_invariants_safe:
        return AdmissionResult(required_pair_count=0, status=AdmissionStatus.REJECTED_SAFETY_INVARIANT, reason_codes=("SAFETY_INVARIANT_FAILED",), safety_invariant_results=request.safety_invariant_results, **base)
    if not request.environment_valid:
        return AdmissionResult(required_pair_count=0, status=AdmissionStatus.INCONCLUSIVE_ENVIRONMENT, reason_codes=("ENVIRONMENT_MISMATCH",), **base)
    required_metrics = [metric for metric in request.metrics if metric.required and metric.applicable]
    if any(len(metric.baseline_values) == 0 or len(metric.baseline_values) != len(metric.candidate_values) for metric in required_metrics):
        return AdmissionResult(required_pair_count=0, status=AdmissionStatus.INCONCLUSIVE_MISSING_METRIC, reason_codes=("REQUIRED_METRIC_MISSING",), **base)
    primary = next((metric for metric in required_metrics if metric.metric_key == request.primary_metric_key), None)
    if primary is None:
        return AdmissionResult(required_pair_count=0, status=AdmissionStatus.INCONCLUSIVE_MISSING_METRIC, reason_codes=("PRIMARY_METRIC_MISSING",), **base)
    required_by_metric = {metric.metric_key + "|" + metric.scope_type + "|" + metric.scope_id: max(MINIMUM_OBSERVATIONS, settings.candidate_pairs or settings.minimum_candidate_pairs or 0) for metric in required_metrics}
    if request.profile != BenchmarkProfile.SMOKE:
        maximum = settings.maximum_candidate_pairs or 0
        try:
            requirements = [_required_for_metric(metric, maximum) for metric in required_metrics]
            requirements.append(_required_for_primary(primary, maximum))
        except ValueError:
            return AdmissionResult(required_pair_count=0, status=AdmissionStatus.INCONCLUSIVE_MISSING_METRIC, reason_codes=("INVALID_METRIC_DATA",), **base)
        required_pairs = max(MINIMUM_OBSERVATIONS, settings.minimum_candidate_pairs or 0, *requirements)
        if required_pairs > maximum:
            return AdmissionResult(required_pair_count=required_pairs, status=AdmissionStatus.INCONCLUSIVE_NOISE, reason_codes=("AA_CALIBRATION_EXCEEDS_PROFILE_MAXIMUM",), **base)
        try:
            required_by_metric = {
                metric.metric_key + "|" + metric.scope_type + "|" + metric.scope_id: max(MINIMUM_OBSERVATIONS, _required_for_metric(metric, maximum))
                for metric in required_metrics
            }
        except ValueError:
            return AdmissionResult(required_pair_count=0, status=AdmissionStatus.INCONCLUSIVE_MISSING_METRIC, reason_codes=("INVALID_METRIC_DATA",), **base)
    else:
        required_pairs = max(required_by_metric.values(), default=MINIMUM_OBSERVATIONS)
    if any(len(metric.baseline_values) < required_by_metric[metric.metric_key + "|" + metric.scope_type + "|" + metric.scope_id] for metric in required_metrics):
        return AdmissionResult(required_pair_count=required_pairs, status=AdmissionStatus.INCONCLUSIVE_MISSING_METRIC, reason_codes=("INSUFFICIENT_CANDIDATE_PAIRS",), **base)
    try:
        protected = tuple(evaluate_non_regression(metric, request.evaluation_run_id, settings.bootstrap_samples, settings.confidence) for metric in required_metrics)
        primary_result = evaluate_primary_benefit(primary, request.evaluation_run_id, settings.bootstrap_samples, settings.confidence)
        family_upper_bound = paired_max_statistic_upper_bound(required_metrics, request.evaluation_run_id, settings.bootstrap_samples, settings.confidence)
    except ValueError:
        return AdmissionResult(required_pair_count=required_pairs, status=AdmissionStatus.INCONCLUSIVE_MISSING_METRIC, reason_codes=("INVALID_METRIC_DATA",), **base)
    if any(not result.passed for result in protected) or family_upper_bound > EPSILON:
        return AdmissionResult(required_pair_count=required_pairs, status=AdmissionStatus.REJECTED_REGRESSION, reason_codes=("PROTECTED_METRIC_REGRESSION", "FAMILY_WISE_PROTECTION_FAILED") if family_upper_bound > EPSILON else ("PROTECTED_METRIC_REGRESSION",), protected_metric_results=protected, primary_benefit_result=primary_result, family_wise_passed=family_upper_bound <= EPSILON, family_wise_upper_bound=family_upper_bound, **base)
    if not primary_result.benefit_passed:
        return AdmissionResult(required_pair_count=required_pairs, status=AdmissionStatus.REJECTED_NO_MEANINGFUL_BENEFIT, reason_codes=("PRIMARY_BENEFIT_NOT_PROVEN",), protected_metric_results=protected, primary_benefit_result=primary_result, family_wise_passed=True, family_wise_upper_bound=family_upper_bound, **base)
    return AdmissionResult(required_pair_count=required_pairs, status=AdmissionStatus.ADMITTED, reason_codes=(), protected_metric_results=protected, primary_benefit_result=primary_result, family_wise_passed=True, family_wise_upper_bound=family_upper_bound, **base)


def _required_for_metric(metric: MetricEvaluationInput, maximum_pairs: int) -> int:
    reference = calculate_baseline_reference(metric.baseline_values, metric.policy.comparison_mode)
    margin = calculate_transformed_regression_margin(reference, calculate_allowed_regression(reference, metric.policy), metric.policy)
    return estimate_required_pairs(metric.aa_scores, margin, maximum_pairs)


def _required_for_primary(metric: MetricEvaluationInput, maximum_pairs: int) -> int:
    return estimate_required_pairs(metric.aa_scores, calculate_transformed_minimum_benefit(metric.policy.direction, metric.policy.minimum_benefit), maximum_pairs)


def _bootstrap_seed(evaluation_run_id: str, metric: MetricEvaluationInput) -> int:
    payload = "|".join((evaluation_run_id, metric.metric_key, metric.scope_type, metric.scope_id, "bootstrap"))
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


def _finite_array(values: Iterable[float]) -> np.ndarray[Any, Any]:
    array = np.asarray(tuple(values), dtype=float)
    if not np.all(np.isfinite(array)):
        raise ValueError("Metric observations must be finite.")
    return cast(np.ndarray[Any, Any], array)


def _validate_value(value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError("Metric values must be finite and non-negative.")
