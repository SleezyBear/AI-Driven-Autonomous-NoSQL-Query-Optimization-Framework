"""768-dimensional experience retrieval and ranking-only prioritization."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Protocol

EMBEDDING_DIMENSIONS = 768
EMBEDDING_MODEL = "embeddinggemma"


@dataclass(frozen=True)
class ExperienceRecord:
    """A literal-safe historical outcome represented by an EmbeddingGemma vector."""

    experience_id: str
    candidate_id: str
    outcome: str
    embedding: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError("Experience embeddings must have exactly 768 dimensions.")


class ExperienceRepository(Protocol):
    """Persistence/retrieval boundary; PostgreSQL pgvector backs durable implementations."""

    def add(self, record: ExperienceRecord) -> None:
        """Persist one validated experience record."""

    def nearest(self, embedding: tuple[float, ...], limit: int) -> tuple[ExperienceRecord, ...]:
        """Return nearest records in deterministic similarity order."""


class InMemoryExperienceRepository:
    """Deterministic test double mirroring pgvector nearest-neighbor semantics."""

    def __init__(self) -> None:
        self._records: list[ExperienceRecord] = []

    def add(self, record: ExperienceRecord) -> None:
        self._records.append(record)

    def nearest(self, embedding: tuple[float, ...], limit: int) -> tuple[ExperienceRecord, ...]:
        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError("Experience embeddings must have exactly 768 dimensions.")
        ranked = sorted(self._records, key=lambda record: (-_cosine_similarity(embedding, record.embedding), record.experience_id))
        return tuple(ranked[:limit])


class ExperienceMemory:
    """Retrieve historical outcomes solely to prioritize existing candidate IDs."""

    def __init__(self, repository: ExperienceRepository) -> None:
        self._repository = repository

    def record(self, experience: ExperienceRecord) -> None:
        self._repository.add(experience)

    def prioritize(self, candidate_ids: tuple[str, ...], embedding: tuple[float, ...], enabled: bool = True) -> tuple[str, ...]:
        """Reorder candidates by relevant positive history; never add candidates or alter policy."""
        if not enabled:
            return candidate_ids
        scores: dict[str, int] = {candidate_id: 0 for candidate_id in candidate_ids}
        for record in self._repository.nearest(embedding, limit=20):
            if record.candidate_id in scores and record.outcome == "ADMITTED":
                scores[record.candidate_id] += 1
        return tuple(sorted(candidate_ids, key=lambda candidate_id: (-scores[candidate_id], candidate_id)))


def _cosine_similarity(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    numerator = sum(left * right for left, right in zip(first, second))
    denominator = sqrt(sum(value * value for value in first)) * sqrt(sum(value * value for value in second))
    return numerator / denominator if denominator else 0.0
