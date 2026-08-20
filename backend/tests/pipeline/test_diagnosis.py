"""Phase 24 acceptance tests for the bounded complete diagnosis pipeline."""

import pytest

from app.admission.models import AdmissionStatus
from app.ai.provider import FakeAIProvider
from app.experience.memory import EMBEDDING_DIMENSIONS, ExperienceMemory, InMemoryExperienceRepository
from app.metrics.collector import MetricSnapshot
from app.pipeline.diagnosis import DiagnosisPipeline, MAX_INITIAL_CANDIDATES
from app.workloads.snapshots import EnvironmentFingerprint, WorkloadSnapshotBuilder


def _snapshot() -> object:
    metrics = MetricSnapshot(None, None, None, 0, 0, 0, None, None, None, None, None, None, 0, 0, 0, 0, 0, 0)
    return WorkloadSnapshotBuilder.build([], [], metrics, EnvironmentFingerprint.from_mapping({"mongo": "8"}))


@pytest.mark.asyncio
async def test_complete_pipeline_evaluates_at_most_three_deterministic_candidates() -> None:
    pipeline = DiagnosisPipeline(FakeAIProvider(), ExperienceMemory(InMemoryExperienceRepository()))
    evaluated: list[str] = []

    async def sandbox(candidate_id: str) -> str:
        evaluated.append(candidate_id)
        return "sandbox:" + candidate_id

    result = await pipeline.run(_snapshot, lambda _: "evidence", lambda _: ("candidate-5", "candidate-4", "candidate-3", "candidate-2", "candidate-1"), (0.0,) * EMBEDDING_DIMENSIONS, sandbox, lambda _: AdmissionStatus.ADMITTED)

    assert result.stages == ("snapshot", "deterministic_evidence", "deterministic_candidate_generation", "experience_retrieval", "llm_diagnosis", "llm_ranking", "sandbox_evaluation", "deterministic_admission")
    assert len(result.evaluated) == MAX_INITIAL_CANDIDATES
    assert [item.candidate_id for item in result.evaluated] == evaluated
    assert all(item.admission_status == AdmissionStatus.ADMITTED for item in result.evaluated)
