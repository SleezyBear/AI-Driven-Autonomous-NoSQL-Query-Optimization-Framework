"""R14 simultaneous-protection and boundary-semantic tests."""

from app.admission.models import AdmissionRequest, AdmissionStatus, BenchmarkProfile, ComparisonMode, MetricDirection, MetricEvaluationInput
from app.admission.policy import DEFAULT_POLICIES
from app.admission.statistics import evaluate_candidate_admission, paired_max_statistic_upper_bound, transform_benefit, transform_regression


def _metric(scope: str, candidate: tuple[float, ...]) -> MetricEvaluationInput:
    return MetricEvaluationInput("p95_latency_ms", "QUERY_SHAPE", scope, DEFAULT_POLICIES["p95_latency_ms"], (100.0,) * len(candidate), candidate)


def test_each_protected_metric_must_individually_meet_the_pair_minimum() -> None:
    request = AdmissionRequest("candidate", "per-metric", BenchmarkProfile.SMOKE, "p95_latency_ms", (_metric("enough", (80, 80, 80)), _metric("short", (80, 80))))

    assert evaluate_candidate_admission(request).status is AdmissionStatus.INCONCLUSIVE_MISSING_METRIC


def test_higher_is_better_zero_cases_have_explicit_correct_signs() -> None:
    assert transform_regression(0, 1, MetricDirection.HIGHER_IS_BETTER, ComparisonMode.LOG_RATIO) < 0
    assert transform_regression(1, 0, MetricDirection.HIGHER_IS_BETTER, ComparisonMode.LOG_RATIO) > 0
    assert transform_benefit(0, 1, MetricDirection.HIGHER_IS_BETTER) > 0
    assert transform_benefit(1, 0, MetricDirection.HIGHER_IS_BETTER) < 0


def test_paired_max_statistic_protects_many_metrics_simultaneously() -> None:
    safe_family = tuple(_metric(f"shape-{index}", (80, 80, 80, 80, 80)) for index in range(20))
    regressing_family = safe_family[:-1] + (_metric("regressing", (110, 110, 110, 110, 110)),)

    assert paired_max_statistic_upper_bound(safe_family, "family-safe", 2_000, 0.95) <= 0
    assert paired_max_statistic_upper_bound(regressing_family, "family-regression", 2_000, 0.95) > 0


def test_many_metric_regression_is_rejected_by_family_wise_gate() -> None:
    metrics = tuple(_metric(f"shape-{index}", (80, 80, 80)) for index in range(19)) + (_metric("regressing", (110, 110, 110)),)
    request = AdmissionRequest("candidate", "family-admission", BenchmarkProfile.SMOKE, "p95_latency_ms", metrics)

    result = evaluate_candidate_admission(request)

    assert result.status is AdmissionStatus.REJECTED_REGRESSION
    assert result.family_wise_passed is False
    assert "FAMILY_WISE_PROTECTION_FAILED" in result.reason_codes
