"""R19C real PostgreSQL optimization-job identity and recovery coverage."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.autonomy.policy import DeploymentMode
from app.db.repositories import create_repositories
from app.runs.service import OptimizationRunCreationService
from app.worker.durable import DurableJobWorker, JobRepository
from app.worker.service import JobDispatcher, OptimizationJobHandler


async def _run_and_job(engine: object) -> tuple[object, object, object, str]:
    marker = uuid4().hex
    async with engine.begin() as connection:  # type: ignore[union-attr]
        user = (await connection.execute(text("INSERT INTO users (id,created_at,updated_at,email,password_hash,role,status,failed_login_count) VALUES(gen_random_uuid(),now(),now(),:email,'hash','OPERATOR','ACTIVE',0) RETURNING id"), {"email": f"{marker}@example.test"})).scalar_one()
        target = (await connection.execute(text("INSERT INTO targets (id,created_at,updated_at,owner_user_id,name,deployment_mode,state,connection_label,is_active) VALUES(gen_random_uuid(),now(),now(),:owner,:name,'APPROVAL_CONTROLLED','ACTIVE','r19c',true) RETURNING id"), {"owner": user, "name": marker})).scalar_one()
    created = await OptimizationRunCreationService(engine).create_run_with_initial_job(target_id=target, requested_by_user_id=user, deployment_mode=DeploymentMode.APPROVAL_CONTROLLED, primary_metric_key=None)
    return user, target, created.run["id"], created.job_id


async def _cleanup(engine: object, target: object, user: object) -> None:
    async with engine.begin() as connection:  # type: ignore[union-attr]
        await connection.execute(text("DELETE FROM jobs WHERE optimization_run_id IN (SELECT id FROM optimization_runs WHERE target_id=:target)"), {"target": target})
        await connection.execute(text("DELETE FROM optimization_runs WHERE target_id=:target"), {"target": target})
        await connection.execute(text("DELETE FROM targets WHERE id=:target"), {"target": target})
        await connection.execute(text("DELETE FROM users WHERE id=:user"), {"user": user})


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["COMPLETED", "ROLLED_BACK", "ROLLBACK_BLOCKED", "FAILED"])
async def test_terminal_runs_complete_job_idempotently_without_workflow(
    terminal: str, disposable_worker_database: str
) -> None:
    engine = create_async_engine(disposable_worker_database)
    user, target, run_id, job_id = await _run_and_job(engine)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE optimization_runs "
                    "SET status=CAST(:status AS run_status), "
                    "completion_reason=CASE WHEN :status='COMPLETED' "
                    "THEN 'LEGACY_COMPLETED'::run_completion_reason ELSE NULL END "
                    "WHERE id=:id"
                ),
                {"status": terminal, "id": run_id},
            )
        dispatcher = JobDispatcher(OptimizationJobHandler(create_repositories(engine)))
        repository = JobRepository(engine)
        claimed_job_ids: list[str] = []
        claim = repository.claim

        async def record_claim(worker_id: str, *, payload_tag: str | None = None) -> object:
            job = await claim(worker_id, payload_tag=payload_tag)
            if job is not None:
                claimed_job_ids.append(job.id)
            return job

        repository.claim = record_claim  # type: ignore[method-assign]
        assert await DurableJobWorker(repository, "terminal-worker").run_once(dispatcher.dispatch)
        assert claimed_job_ids == [job_id]
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT status FROM jobs WHERE id=:id"), {"id": job_id})).scalar_one() == "COMPLETED"
            run = (
                await connection.execute(
                    text("SELECT status::text,completion_reason::text FROM optimization_runs WHERE id=:id"),
                    {"id": run_id},
                )
            ).mappings().one()
            assert run["status"] == terminal
            assert run["completion_reason"] == ("LEGACY_COMPLETED" if terminal == "COMPLETED" else None)
    finally:
        await _cleanup(engine, target, user)
        await engine.dispose()


@pytest.mark.asyncio
async def test_nonterminal_optimization_job_fails_permanently_without_orchestrator_and_recovers_same_row(
    disposable_worker_database: str,
) -> None:
    engine = create_async_engine(disposable_worker_database)
    user, target, run_id, job_id = await _run_and_job(engine)
    try:
        repository = JobRepository(engine, lease_duration=timedelta(milliseconds=100))
        dispatcher = JobDispatcher(OptimizationJobHandler(create_repositories(engine)))
        assert await DurableJobWorker(repository, "worker-a").run_once(dispatcher.dispatch)
        async with engine.connect() as connection:
            job = (await connection.execute(text("SELECT status,attempts,last_error_code,failed_at FROM jobs WHERE id=:id"), {"id": job_id})).mappings().one()
            assert dict(job)["status"] == "FAILED" and dict(job)["attempts"] == 1 and dict(job)["last_error_code"] == "ORCHESTRATION_UNAVAILABLE" and dict(job)["failed_at"] is not None
            assert (await connection.execute(text("SELECT status::text FROM optimization_runs WHERE id=:id"), {"id": run_id})).scalar_one() == "CREATED"
        assert await repository.claim("worker-b") is None
    finally:
        await _cleanup(engine, target, user)
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_restart_after_lease_expiry_recovers_the_same_authoritative_job_row(
    disposable_worker_database: str,
) -> None:
    engine = create_async_engine(disposable_worker_database)
    user, target, run_id, job_id = await _run_and_job(engine)
    try:
        repository = JobRepository(engine, lease_duration=timedelta(milliseconds=150))
        claimed_by_a = await repository.claim("crashed-worker-a")
        assert claimed_by_a is not None and claimed_by_a.id == job_id and claimed_by_a.optimization_run_id == str(run_id)
        # Simulate a process disappearance: no completion, release, or heartbeat.
        await asyncio.sleep(0.2)
        recovered_by_b = await JobRepository(engine, lease_duration=timedelta(milliseconds=150)).claim("restarted-worker-b")
        assert recovered_by_b is not None
        assert recovered_by_b.id == job_id
        assert recovered_by_b.optimization_run_id == str(run_id)
        assert recovered_by_b.attempts == 2
        async with engine.connect() as connection:
            row = (await connection.execute(text("SELECT count(*) AS jobs, lease_owner, status FROM jobs WHERE optimization_run_id=:run_id GROUP BY lease_owner,status"), {"run_id": run_id})).mappings().one()
            assert row["jobs"] == 1 and row["lease_owner"] == "restarted-worker-b" and row["status"] == "RUNNING"
            assert (await connection.execute(text("SELECT status::text FROM optimization_runs WHERE id=:id"), {"id": run_id})).scalar_one() == "CREATED"
        await repository.fail(recovered_by_b, "restarted-worker-b", "ORCHESTRATION_UNAVAILABLE", permanent=True)
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT status,last_error_code FROM jobs WHERE id=:id"), {"id": job_id})).mappings().one()["last_error_code"] == "ORCHESTRATION_UNAVAILABLE"
    finally:
        await _cleanup(engine, target, user)
        await engine.dispose()
