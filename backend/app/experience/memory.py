"""768-dimensional experience retrieval and ranking-only prioritization."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import models

EMBEDDING_DIMENSIONS = 768
EMBEDDING_MODEL = "embeddinggemma"


@dataclass(frozen=True)
class ExperienceRecord:
    """A literal-safe historical outcome represented by an EmbeddingGemma vector."""

    experience_id: str
    candidate_id: str
    outcome: str
    embedding: tuple[float, ...]
    adapter_type: str = "mongodb"
    action_type: str = "CREATE_INDEX"
    query_structure_summary: dict[str, object] | None = None
    workload_features: dict[str, object] | None = None
    bottleneck: str | None = None
    candidate_summary: dict[str, object] | None = None
    prediction: dict[str, object] | None = None
    admission_outcome: str | None = None
    actual_postdeploy_outcome: str | None = None
    rollback_outcome: str | None = None
    embedding_model: str = EMBEDDING_MODEL
    embedding_model_version: str = "unknown"

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


class PostgresExperienceRepository:
    """Durable pgvector experience store with action-family-gated retrieval."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def add(self, record: ExperienceRecord) -> str:
        """Persist a literal-safe experience and return its database identifier."""
        candidate_id = UUID(record.candidate_id) if _is_uuid(record.candidate_id) else None
        values = {
            "candidate_id": candidate_id,
            "outcome": record.outcome,
            "embedding": list(record.embedding),
            "evidence": {},
            "adapter_type": record.adapter_type,
            "action_type": record.action_type,
            "query_structure_summary": record.query_structure_summary or {},
            "workload_features": record.workload_features or {},
            "bottleneck": record.bottleneck,
            "candidate_summary": record.candidate_summary or {},
            "prediction": record.prediction or {},
            "admission_outcome": record.admission_outcome or record.outcome,
            "actual_postdeploy_outcome": record.actual_postdeploy_outcome,
            "rollback_outcome": record.rollback_outcome,
            "embedding_model": record.embedding_model,
            "embedding_model_version": record.embedding_model_version,
        }
        from app.db.repositories import ExperienceRepository as ControlPlaneExperienceRepository

        persisted = await ControlPlaneExperienceRepository(self._engine).create(**values)
        return str(persisted["id"])

    async def nearest(self, embedding: tuple[float, ...], action_type: str, limit: int) -> tuple[ExperienceRecord, ...]:
        """Return only compatible action-family precedents in cosine-distance order."""
        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError("Experience embeddings must have exactly 768 dimensions.")
        if limit <= 0:
            return ()
        table = models.ExperienceRecord.__table__
        distance = table.c.embedding.cosine_distance(list(embedding))
        statement = (
            select(table)
            .where(table.c.action_type == action_type, table.c.embedding.is_not(None))
            .order_by(distance, table.c.created_at, table.c.id)
            .limit(limit)
        )
        async with self._engine.connect() as connection:
            result = await connection.execute(statement)
            return tuple(_from_row(row) for row in result.mappings())


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


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _from_row(row: object) -> ExperienceRecord:
    mapping = row  # SQLAlchemy RowMapping supports mapping-style access at runtime.
    return ExperienceRecord(
        experience_id=str(mapping["id"]),  # type: ignore[index]
        candidate_id=str(mapping["candidate_id"] or mapping["id"]),  # type: ignore[index]
        outcome=str(mapping["outcome"] or "UNKNOWN"),  # type: ignore[index]
        embedding=tuple(mapping["embedding"]),  # type: ignore[index]
        adapter_type=str(mapping["adapter_type"]),  # type: ignore[index]
        action_type=str(mapping["action_type"]),  # type: ignore[index]
        query_structure_summary=dict(mapping["query_structure_summary"]),  # type: ignore[index]
        workload_features=dict(mapping["workload_features"]),  # type: ignore[index]
        bottleneck=mapping["bottleneck"],  # type: ignore[index]
        candidate_summary=dict(mapping["candidate_summary"]),  # type: ignore[index]
        prediction=dict(mapping["prediction"]),  # type: ignore[index]
        admission_outcome=mapping["admission_outcome"],  # type: ignore[index]
        actual_postdeploy_outcome=mapping["actual_postdeploy_outcome"],  # type: ignore[index]
        rollback_outcome=mapping["rollback_outcome"],  # type: ignore[index]
        embedding_model=str(mapping["embedding_model"]),  # type: ignore[index]
        embedding_model_version=str(mapping["embedding_model_version"]),  # type: ignore[index]
    )
