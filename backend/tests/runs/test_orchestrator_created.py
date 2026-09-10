"""R19D persisted CREATED-boundary orchestration tests using real PostgreSQL."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.autonomy.policy import DeploymentMode
from app.runs.orchestrator import OptimizationRunOrchestrator, OrchestrationInvariantError, OrchestrationOutcome
from app.runs.service import OptimizationRunCreationService
from app.worker.durable import ExecutionContext


DATABASE_URL = "postgresql+asyncpg://control_plane:control_plane_dev_only@127.0.0.1:5432/control_plane"


async def _created_run(engine: object, *, mapping: bool = True) -> tuple[UUID, UUID, UUID, UUID]:
    marker = uuid4().hex
    async with engine.begin() as connection:  # type: ignore[union-attr]
        user = UUID(str((await connection.execute(text("INSERT INTO users (id,created_at,updated_at,email,password_hash,role,status,failed_login_count) VALUES(gen_random_uuid(),now(),now(),:email,'hash','OPERATOR','ACTIVE',0) RETURNING id"), {"email": f"{marker}@example.test"})).scalar_one()))
        monitored = UUID(str((await connection.execute(text("INSERT INTO targets (id,created_at,updated_at,owner_user_id,name,deployment_mode,state,connection_label,is_active) VALUES(gen_random_uuid(),now(),now(),:owner,:name,'APPROVAL_CONTROLLED','ACTIVE','monitored',true) RETURNING id"), {"owner": user, "name": f"monitored-{marker}"})).scalar_one()))
        evaluation = UUID(str((await connection.execute(text("INSERT INTO targets (id,created_at,updated_at,owner_user_id,name,deployment_mode,state,connection_label,is_active) VALUES(gen_random_uuid(),now(),now(),:owner,:name,'APPROVAL_CONTROLLED','ACTIVE','evaluation',true) RETURNING id"), {"owner": user, "name": f"evaluation-{marker}"})).scalar_one()))
        if mapping:
            await connection.execute(text("INSERT INTO evaluation_mappings (id,created_at,updated_at,target_id,evaluation_target_id,mapping_status) VALUES(gen_random_uuid(),now(),now(),:target,:evaluation,'ACTIVE')"), {"target": monitored, "evaluation": evaluation})
    created = await OptimizationRunCreationService(engine).create_run_with_initial_job(
        target_id=monitored,
        requested_by_user_id=user,
        deployment_mode=DeploymentMode.APPROVAL_CONTROLLED,
        primary_metric_key=None,
    )
    return user, monitored, evaluation, UUID(str(created.run["id"]))


async def _cleanup(engine: object, user: UUID, monitored: UUID, evaluation: UUID) -> None:
    async with engine.begin() as connection:  # type: ignore[union-attr]
        await connection.execute(text("DELETE FROM jobs WHERE optimization_run_id IN (SELECT id FROM optimization_runs WHERE target_id=:target)"), {"target": monitored})
        await connection.execute(text("DELETE FROM optimization_runs WHERE target_id=:target"), {"target": monitored})
        await connection.execute(text("DELETE FROM evaluation_mappings WHERE target_id=:target"), {"target": monitored})
        await connection.execute(text("DELETE FROM targets WHERE id IN (:monitored,:evaluation)"), {"monitored": monitored, "evaluation": evaluation})
        await connection.execute(text("DELETE FROM users WHERE id=:user"), {"user": user})


@pytest.mark.asyncio
async def test_created_run_advances_to_snapshotting_and_blocks_without_completed_telemetry() -> None:
    engine = create_async_engine(DATABASE_URL)
    user, monitored, evaluation, run_id = await _created_run(engine)
    try:
        orchestrator = OptimizationRunOrchestrator(engine)
        result = await orchestrator.run(run_id, ExecutionContext(asyncio.Event()))
        assert result.outcome is OrchestrationOutcome.PROGRESSED and result.status.value == "SNAPSHOTTING"
        resumed = await OptimizationRunOrchestrator(engine).run(run_id, ExecutionContext(asyncio.Event()))
        assert resumed.outcome is OrchestrationOutcome.BLOCKED and resumed.blocker == "NO_COMPLETED_TELEMETRY"
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT status::text FROM optimization_runs WHERE id=:id"), {"id": run_id})).scalar_one() == "SNAPSHOTTING"
    finally:
        await _cleanup(engine, user, monitored, evaluation)
        await engine.dispose()


@pytest.mark.asyncio
async def test_created_run_without_distinct_mapping_fails_closed_without_transition() -> None:
    engine = create_async_engine(DATABASE_URL)
    user, monitored, evaluation, run_id = await _created_run(engine, mapping=False)
    try:
        with pytest.raises(OrchestrationInvariantError, match="valid distinct evaluation target"):
            await OptimizationRunOrchestrator(engine).run(run_id, ExecutionContext(asyncio.Event()))
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT status::text FROM optimization_runs WHERE id=:id"), {"id": run_id})).scalar_one() == "CREATED"
    finally:
        await _cleanup(engine, user, monitored, evaluation)
        await engine.dispose()


@pytest.mark.asyncio
async def test_lease_loss_before_created_transition_prevents_transition() -> None:
    engine = create_async_engine(DATABASE_URL)
    user, monitored, evaluation, run_id = await _created_run(engine)
    lost = asyncio.Event()
    lost.set()
    try:
        with pytest.raises(Exception, match="lease ownership"):
            await OptimizationRunOrchestrator(engine).run(run_id, ExecutionContext(lost))
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT status::text FROM optimization_runs WHERE id=:id"), {"id": run_id})).scalar_one() == "CREATED"
    finally:
        await _cleanup(engine, user, monitored, evaluation)
        await engine.dispose()
