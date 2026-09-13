"""R19B PostgreSQL integration tests for lifecycle persistence and atomic creation."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.autonomy.policy import DeploymentMode
from app.db import models
from app.db.repositories import RunRepository
from app.runs.service import OptimizationRunCreationService
from app.worker.durable import JobKind, JobRepository


DATABASE_URL = "postgresql+asyncpg://control_plane:control_plane_dev_only@127.0.0.1:5432/control_plane"


@pytest.mark.asyncio
async def test_atomic_run_job_creation_and_restart_persistence() -> None:
    engine = create_async_engine(DATABASE_URL)
    marker = uuid4().hex
    try:
        async with engine.begin() as connection:
            user_id = (await connection.execute(text("INSERT INTO users (id, created_at, updated_at, email, password_hash, role, status, failed_login_count) VALUES (gen_random_uuid(), now(), now(), :email, 'hash', 'OPERATOR', 'ACTIVE', 0) RETURNING id"), {"email": f"{marker}@example.test"})).scalar_one()
            target_id = (await connection.execute(text("INSERT INTO targets (id, created_at, updated_at, owner_user_id, name, deployment_mode, state, connection_label, is_active) VALUES (gen_random_uuid(), now(), now(), :owner, :name, 'APPROVAL_CONTROLLED', 'ACTIVE', 'test', true) RETURNING id"), {"owner": user_id, "name": marker})).scalar_one()
        created = await OptimizationRunCreationService(engine).create_run_with_initial_job(target_id=target_id, requested_by_user_id=user_id, deployment_mode=DeploymentMode.APPROVAL_CONTROLLED, primary_metric_key="p99_latency_ms")
        assert created.run["status"] is models.RunStatus.CREATED
        async with engine.connect() as connection:
            job = (await connection.execute(text("SELECT optimization_run_id, kind FROM jobs WHERE id = :id"), {"id": created.job_id})).mappings().one()
        assert job["optimization_run_id"] == created.run["id"]
        assert job["kind"] == "OPTIMIZATION"
        run_id = created.run["id"]
    finally:
        await engine.dispose()

    restarted = create_async_engine(DATABASE_URL)
    try:
        assert await RunRepository(restarted).get(run_id) is not None
    finally:
        async with restarted.begin() as connection:
            await connection.execute(text("DELETE FROM jobs WHERE optimization_run_id = :id"), {"id": run_id})
            await connection.execute(text("DELETE FROM optimization_runs WHERE id = :id"), {"id": run_id})
            await connection.execute(text("DELETE FROM targets WHERE id = :id"), {"id": target_id})
            await connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        await restarted.dispose()


def test_persisted_and_in_memory_lifecycle_enums_remain_identical() -> None:
    from app.state_machine.optimization import OptimizationState

    assert {state.value for state in models.RunStatus} == {state.value for state in OptimizationState}


@pytest.mark.asyncio
async def test_persisted_transition_and_primary_metric_guards() -> None:
    engine = create_async_engine(DATABASE_URL)
    marker = uuid4().hex
    try:
        async with engine.begin() as connection:
            user_id = (await connection.execute(text("INSERT INTO users (id, created_at, updated_at, email, password_hash, role, status, failed_login_count) VALUES (gen_random_uuid(), now(), now(), :email, 'hash', 'OPERATOR', 'ACTIVE', 0) RETURNING id"), {"email": f"{marker}@example.test"})).scalar_one()
            target_id = (await connection.execute(text("INSERT INTO targets (id, created_at, updated_at, owner_user_id, name, deployment_mode, state, connection_label, is_active) VALUES (gen_random_uuid(), now(), now(), :owner, :name, 'APPROVAL_CONTROLLED', 'ACTIVE', 'test', true) RETURNING id"), {"owner": user_id, "name": marker})).scalar_one()
        created = await OptimizationRunCreationService(engine).create_run_with_initial_job(target_id=target_id, requested_by_user_id=user_id, deployment_mode=DeploymentMode.APPROVAL_CONTROLLED, primary_metric_key=None)
        runs = RunRepository(engine)
        assert created.run["workload_snapshot_id"] is None
        with pytest.raises(ValueError, match="cannot transition"):
            await runs.transition(created.run["id"], models.RunStatus.EVALUATING)
        transitioned = await runs.transition(created.run["id"], models.RunStatus.SNAPSHOTTING)
        assert transitioned["status"] is models.RunStatus.SNAPSHOTTING
        with pytest.raises(ValueError, match="workload snapshot"):
            await runs.transition(created.run["id"], models.RunStatus.DIAGNOSING)
        async with engine.begin() as connection:
            window_id = (await connection.execute(text("INSERT INTO telemetry_windows (id, created_at, updated_at, target_id, started_at, ended_at, source, status) VALUES (gen_random_uuid(), now(), now(), :target, now(), now(), 'test', 'COMPLETE') RETURNING id"), {"target": target_id})).scalar_one()
            snapshot_id = (await connection.execute(text("INSERT INTO workload_snapshots (id, created_at, updated_at, target_id, telemetry_window_id, snapshot, fingerprint) VALUES (gen_random_uuid(), now(), now(), :target, :window, '{}'::jsonb, :fingerprint) RETURNING id"), {"target": target_id, "window": window_id, "fingerprint": marker})).scalar_one()
        attached = await runs.attach_workload_snapshot(created.run["id"], snapshot_id)
        assert attached["workload_snapshot_id"] == snapshot_id
        assert (await runs.transition(created.run["id"], models.RunStatus.DIAGNOSING))["status"] is models.RunStatus.DIAGNOSING
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE optimization_runs SET status = 'RANKING'::run_status WHERE id = :id"), {"id": created.run["id"]})
        with pytest.raises(ValueError, match="primary metric"):
            await runs.transition(created.run["id"], models.RunStatus.CALIBRATING)
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE optimization_runs SET primary_metric_key = 'p99_latency_ms' WHERE id = :id"), {"id": created.run["id"]})
        with pytest.raises(ValueError, match="durable candidate ranking"):
            await runs.transition(created.run["id"], models.RunStatus.CALIBRATING)
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM jobs WHERE optimization_run_id IN (SELECT id FROM optimization_runs WHERE target_id = :id)"), {"id": target_id})
            await connection.execute(text("DELETE FROM optimization_runs WHERE target_id = :id"), {"id": target_id})
            # The snapshot is deliberately immutable history.  Do not make this
            # legacy integration test cascade-delete it through its target.
        await engine.dispose()


@pytest.mark.asyncio
async def test_job_insert_failure_rolls_back_new_run() -> None:
    class FailingJobs(JobRepository):
        async def enqueue(self, *args: object, **kwargs: object) -> str:
            raise RuntimeError("forced initial job failure")

    engine = create_async_engine(DATABASE_URL)
    marker = uuid4().hex
    try:
        async with engine.begin() as connection:
            user_id = (await connection.execute(text("INSERT INTO users (id, created_at, updated_at, email, password_hash, role, status, failed_login_count) VALUES (gen_random_uuid(), now(), now(), :email, 'hash', 'OPERATOR', 'ACTIVE', 0) RETURNING id"), {"email": f"{marker}@example.test"})).scalar_one()
            target_id = (await connection.execute(text("INSERT INTO targets (id, created_at, updated_at, owner_user_id, name, deployment_mode, state, connection_label, is_active) VALUES (gen_random_uuid(), now(), now(), :owner, :name, 'APPROVAL_CONTROLLED', 'ACTIVE', 'test', true) RETURNING id"), {"owner": user_id, "name": marker})).scalar_one()
        with pytest.raises(RuntimeError, match="forced"):
            await OptimizationRunCreationService(engine, FailingJobs(engine)).create_run_with_initial_job(target_id=target_id, requested_by_user_id=user_id, deployment_mode=DeploymentMode.APPROVAL_CONTROLLED, primary_metric_key="p99_latency_ms")
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT count(*) FROM optimization_runs WHERE target_id = :id"), {"id": target_id})).scalar_one() == 0
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM targets WHERE id = :id"), {"id": target_id})
            await connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_partial_unique_index_rejects_duplicate_initial_job() -> None:
    engine = create_async_engine(DATABASE_URL)
    marker = uuid4().hex
    try:
        async with engine.begin() as connection:
            user_id = (await connection.execute(text("INSERT INTO users (id, created_at, updated_at, email, password_hash, role, status, failed_login_count) VALUES (gen_random_uuid(), now(), now(), :email, 'hash', 'OPERATOR', 'ACTIVE', 0) RETURNING id"), {"email": f"{marker}@example.test"})).scalar_one()
            target_id = (await connection.execute(text("INSERT INTO targets (id, created_at, updated_at, owner_user_id, name, deployment_mode, state, connection_label, is_active) VALUES (gen_random_uuid(), now(), now(), :owner, :name, 'APPROVAL_CONTROLLED', 'ACTIVE', 'test', true) RETURNING id"), {"owner": user_id, "name": marker})).scalar_one()
        created = await OptimizationRunCreationService(engine).create_run_with_initial_job(target_id=target_id, requested_by_user_id=user_id, deployment_mode=DeploymentMode.APPROVAL_CONTROLLED, primary_metric_key="p99_latency_ms")
        with pytest.raises(IntegrityError):
            await JobRepository(engine).enqueue({"run_id": str(created.run["id"]), "target_id": str(target_id)}, optimization_run_id=str(created.run["id"]), kind=JobKind.OPTIMIZATION)
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT count(*) FROM jobs WHERE optimization_run_id = :id AND kind = 'OPTIMIZATION'"), {"id": created.run["id"]})).scalar_one() == 1
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM jobs WHERE optimization_run_id IN (SELECT id FROM optimization_runs WHERE target_id = :id)"), {"id": target_id})
            await connection.execute(text("DELETE FROM optimization_runs WHERE target_id = :id"), {"id": target_id})
            await connection.execute(text("DELETE FROM targets WHERE id = :id"), {"id": target_id})
            await connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        await engine.dispose()
