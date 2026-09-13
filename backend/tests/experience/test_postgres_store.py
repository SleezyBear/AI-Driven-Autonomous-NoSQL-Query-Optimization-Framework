"""R17 integration checks for durable action-family-scoped pgvector memory."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.experience.memory import EMBEDDING_DIMENSIONS, ExperienceRecord, PostgresExperienceRepository


def _vector(value: float) -> tuple[float, ...]:
    return (value,) * EMBEDDING_DIMENSIONS


@pytest.mark.asyncio
async def test_pgvector_experience_survives_restart_and_filters_action_family(disposable_experience_database: str) -> None:
    marker = f"r17-{uuid4()}"
    engine = create_async_engine(disposable_experience_database)
    try:
        repository = PostgresExperienceRepository(engine)
        stored_id = await repository.add(
            ExperienceRecord(
                experience_id="local-index-precedent",
                candidate_id="not-a-database-candidate-id",
                outcome="ADMITTED",
                embedding=_vector(1.0),
                adapter_type="mongodb",
                action_type="CREATE_INDEX",
                query_structure_summary={"shape": "orders-by-customer"},
                workload_features={"p99_ms": 250.0},
                bottleneck=marker,
                candidate_summary={"index": ["customer_id", "created_at"]},
                prediction={"p99_delta": -0.2},
                admission_outcome="ADMITTED",
                actual_postdeploy_outcome="IMPROVED",
                rollback_outcome="NOT_REQUIRED",
                embedding_model="embeddinggemma",
                embedding_model_version="v1",
            )
        )
        await repository.add(
            ExperienceRecord("configuration-precedent", "not-a-database-candidate-id", "ADMITTED", _vector(1.0), action_type="SET_CONFIGURATION", bottleneck=marker)
        )
    finally:
        await engine.dispose()

    restarted_engine = create_async_engine(disposable_experience_database)
    try:
        restarted = PostgresExperienceRepository(restarted_engine)
        matches = await restarted.nearest(_vector(1.0), "CREATE_INDEX", limit=10)

        matching = [record for record in matches if record.experience_id == stored_id]
        assert len(matching) == 1
        record = matching[0]
        assert record.adapter_type == "mongodb"
        assert record.action_type == "CREATE_INDEX"
        assert record.query_structure_summary == {"shape": "orders-by-customer"}
        assert record.actual_postdeploy_outcome == "IMPROVED"
        assert record.embedding_model_version == "v1"
        assert all(item.action_type == "CREATE_INDEX" for item in matches)
    finally:
        async with restarted_engine.begin() as connection:
            await connection.execute(text("DELETE FROM experience_records WHERE bottleneck = :marker"), {"marker": marker})
        await restarted_engine.dispose()
