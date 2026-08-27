"""Orchestrate the frozen diagnosis-to-admission sequence without granting AI authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from app.admission.models import AdmissionStatus
from app.ai.provider import AIProvider, CandidateRanking, Diagnosis
from app.experience.memory import ExperienceMemory
from app.workloads.snapshots import WorkloadSnapshot

MAX_INITIAL_CANDIDATES = 3


@dataclass(frozen=True)
class EvaluatedCandidate:
    """Sandbox and deterministic admission evidence for one bounded candidate."""

    candidate_id: str
    sandbox_result: str
    admission_status: AdmissionStatus


@dataclass(frozen=True)
class DiagnosisPipelineResult:
    """Auditable output of the complete frozen Phase-24 flow."""

    snapshot: WorkloadSnapshot
    evidence: str
    diagnosis: Diagnosis
    ranking: CandidateRanking
    evaluated: tuple[EvaluatedCandidate, ...]
    stages: tuple[str, ...]


class DiagnosisPipeline:
    """Execute snapshot → evidence → candidates → memory → AI → sandbox → admission."""

    def __init__(self, provider: AIProvider, experience_memory: ExperienceMemory) -> None:
        self._provider = provider
        self._experience_memory = experience_memory

    async def run(
        self,
        snapshot_provider: Callable[[], WorkloadSnapshot],
        evidence_builder: Callable[[WorkloadSnapshot], str],
        candidate_generator: Callable[[str], tuple[str, ...]],
        experience_embedding: tuple[float, ...],
        sandbox_evaluate: Callable[[str], Awaitable[str]],
        deterministic_admit: Callable[[str], AdmissionStatus],
    ) -> DiagnosisPipelineResult:
        """Run the complete bounded flow; AI ranking cannot bypass sandbox/admission."""
        snapshot = snapshot_provider()
        evidence = evidence_builder(snapshot)
        generated = candidate_generator(evidence)
        memory_ranked = self._experience_memory.prioritize(generated, experience_embedding)
        try:
            diagnosis = await self._provider.diagnose(evidence)
            ranking = await self._provider.rank_candidates(memory_ranked)
            self._validate_evidence_refs(diagnosis.evidence_refs, evidence)
            self._validate_evidence_refs(ranking.evidence_refs, evidence)
        except Exception:
            # AI is advisory-only. Its unavailability or invalid output must not
            # interrupt deterministic candidate generation, sandboxing, or admission.
            diagnosis = Diagnosis(
                summary="AI advisory output unavailable; deterministic safeguards retained.",
                evidence=(),
                limitations=("AI_UNAVAILABLE_OR_INVALID",),
            )
            ranking = CandidateRanking(candidate_ids=(), rationale="AI advisory output unavailable")
        selected = self._select_known_candidates(generated, ranking.candidate_ids)
        evaluated: list[EvaluatedCandidate] = []
        for candidate_id in selected[:MAX_INITIAL_CANDIDATES]:
            sandbox_result = await sandbox_evaluate(candidate_id)
            evaluated.append(EvaluatedCandidate(candidate_id, sandbox_result, deterministic_admit(sandbox_result)))
        return DiagnosisPipelineResult(snapshot, evidence, diagnosis, ranking, tuple(evaluated), ("snapshot", "deterministic_evidence", "deterministic_candidate_generation", "experience_retrieval", "llm_diagnosis", "llm_ranking", "sandbox_evaluation", "deterministic_admission"))

    @staticmethod
    def _select_known_candidates(generated: tuple[str, ...], ranked: tuple[str, ...]) -> tuple[str, ...]:
        """Retain only deterministic candidates; hallucinated IDs cannot enter evaluation."""
        known = set(generated)
        selected = [candidate_id for candidate_id in ranked if candidate_id in known]
        selected.extend(candidate_id for candidate_id in generated if candidate_id not in selected)
        return tuple(selected)

    @staticmethod
    def _validate_evidence_refs(references: tuple[str, ...], evidence: str) -> None:
        """Reject AI evidence references that are absent from deterministic evidence."""
        if any(reference not in evidence for reference in references):
            raise ValueError("AI response contains a fabricated evidence reference")
