"""Phase 23 acceptance tests for 768-dimensional ranking-only experience memory."""

import pytest

from app.admission.models import AdmissionRequest, AdmissionStatus, BenchmarkProfile, MetricEvaluationInput
from app.admission.policy import DEFAULT_POLICIES
from app.admission.statistics import evaluate_candidate_admission
from app.experience.memory import EMBEDDING_DIMENSIONS, ExperienceMemory, ExperienceRecord, InMemoryExperienceRepository


def _vector(first_value: float) -> tuple[float, ...]:
    return (first_value,) + (0.0,) * (EMBEDDING_DIMENSIONS - 1)


def test_memory_uses_768_dimensions_and_changes_candidate_ranking_only() -> None:
    memory = ExperienceMemory(InMemoryExperienceRepository())
    memory.record(ExperienceRecord("experience-1", "candidate-b", "ADMITTED", _vector(1.0)))

    assert memory.prioritize(("candidate-a", "candidate-b"), _vector(1.0), enabled=False) == ("candidate-a", "candidate-b")
    assert memory.prioritize(("candidate-a", "candidate-b"), _vector(1.0)) == ("candidate-b", "candidate-a")
    metric = MetricEvaluationInput("p95_latency_ms", "GLOBAL", "global", DEFAULT_POLICIES["p95_latency_ms"], (100, 100, 100), (80, 80, 80))
    request = AdmissionRequest("candidate-a", "evaluation", BenchmarkProfile.SMOKE, "p95_latency_ms", (metric,))
    assert evaluate_candidate_admission(request).status == AdmissionStatus.ADMITTED


def test_invalid_embedding_dimension_is_rejected() -> None:
    with pytest.raises(ValueError, match="768"):
        ExperienceRecord("experience", "candidate", "ADMITTED", (1.0,))
