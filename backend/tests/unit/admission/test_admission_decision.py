"""All Phase-15 final-decision paths."""

from app.admission.models import AdmissionRequest, AdmissionStatus, BenchmarkProfile, MetricEvaluationInput
from app.admission.policy import DEFAULT_POLICIES
from app.admission.statistics import evaluate_candidate_admission


def _metric(key: str, baseline: tuple[float, ...], candidate: tuple[float, ...], scope: str = "GLOBAL", aa: tuple[float, ...] = ()) -> MetricEvaluationInput:
    return MetricEvaluationInput(key, scope, key, DEFAULT_POLICIES[key], baseline, candidate, aa_scores=aa)


def _request(metrics: tuple[MetricEvaluationInput, ...], primary: str = "p95_latency_ms", **kwargs: object) -> AdmissionRequest:
    return AdmissionRequest("candidate", "evaluation", BenchmarkProfile.SMOKE, primary, metrics, **kwargs)


def test_safe_benefit_is_admitted() -> None:
    result = evaluate_candidate_admission(_request((_metric("p95_latency_ms", (100, 100, 100), (80, 80, 80)),)))
    assert result.status == AdmissionStatus.ADMITTED
    assert result.primary_benefit_result is not None and result.primary_benefit_result.benefit_passed


def test_minority_query_regression_cannot_be_hidden() -> None:
    result = evaluate_candidate_admission(_request((_metric("p95_latency_ms", (100, 100, 100), (80, 80, 80)), _metric("p95_latency_ms", (100, 100, 100), (150, 150, 150), "QUERY_SHAPE"))))
    assert result.status == AdmissionStatus.REJECTED_REGRESSION


def test_tiny_benefit_is_rejected() -> None:
    assert evaluate_candidate_admission(_request((_metric("p95_latency_ms", (100, 100, 100), (99, 99, 99)),))).status == AdmissionStatus.REJECTED_NO_MEANINGFUL_BENEFIT


def test_cpu_regression_rejects_throughput_candidate() -> None:
    result = evaluate_candidate_admission(_request((_metric("throughput_ops_s", (100, 100, 100), (120, 120, 120)), _metric("cpu_utilization", (0.61, 0.61, 0.61), (0.65, 0.65, 0.65))), "throughput_ops_s"))
    assert result.status == AdmissionStatus.REJECTED_REGRESSION


def test_missing_environment_and_safety_fail_closed_in_precedence_order() -> None:
    metrics = (_metric("p95_latency_ms", (100, 100, 100), (80, 80, 80)),)
    assert evaluate_candidate_admission(_request((), primary="p95_latency_ms")).status == AdmissionStatus.INCONCLUSIVE_MISSING_METRIC
    assert evaluate_candidate_admission(_request(metrics, environment_valid=False)).status == AdmissionStatus.INCONCLUSIVE_ENVIRONMENT
    assert evaluate_candidate_admission(_request(metrics, environment_valid=False, safety_invariants_safe=False)).status == AdmissionStatus.REJECTED_SAFETY_INVARIANT


def test_excessive_aa_noise_is_inconclusive() -> None:
    noisy = _metric("p95_latency_ms", (100,) * 10, (80,) * 10, aa=(-1, 1, -1, 1))
    request = AdmissionRequest("candidate", "evaluation", BenchmarkProfile.AUTONOMOUS, "p95_latency_ms", (noisy,))
    assert evaluate_candidate_admission(request).status == AdmissionStatus.INCONCLUSIVE_NOISE
