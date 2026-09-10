"""R19C real-PostgreSQL lease, retry, and failure-policy tests."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.worker.durable import DurableJobWorker, ExecutionContext, Job, JobRepository, LeaseLostError, PermanentJobError


async def _status(engine: object, job_id: str) -> dict[str, object]:
    async with engine.connect() as connection:  # type: ignore[union-attr]
        return dict((await connection.execute(text("SELECT status, attempts, lease_owner, available_at, failed_at, last_error_code FROM jobs WHERE id=:id"), {"id": job_id})).mappings().one())


@pytest.mark.asyncio
async def test_real_lease_loss_signals_checkpoint_and_allows_recovery(disposable_worker_database: str) -> None:
    engine = create_async_engine(disposable_worker_database)
    repository = JobRepository(engine, lease_duration=timedelta(milliseconds=250))
    tag = uuid4().hex
    job_id = await repository.enqueue({"lease_loss": True, "_queue_tag": tag})
    entered = asyncio.Event()
    observed_loss = asyncio.Event()

    async def handler(job: Job, context: ExecutionContext) -> None:
        assert job.id == job_id
        entered.set()
        while not context.lease_lost.is_set():
            await asyncio.sleep(0.03)
        with pytest.raises(LeaseLostError):
            context.ensure_lease_owned()
        observed_loss.set()
        raise LeaseLostError("lost")

    try:
        task = asyncio.create_task(DurableJobWorker(repository, "worker-a", payload_tag=tag).run_once(handler))
        await asyncio.wait_for(entered.wait(), timeout=1)
        async with engine.connect() as connection:
            owned = (
                await connection.execute(
                    text("SELECT status, lease_owner FROM jobs WHERE id=:id"), {"id": job_id}
                )
            ).mappings().one()
        assert owned["status"] == "RUNNING"
        assert owned["lease_owner"] == "worker-a"
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE jobs SET lease_owner='worker-b' WHERE id=:id"), {"id": job_id})
        with pytest.raises(LeaseLostError):
            await task
        assert observed_loss.is_set()
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE jobs SET lease_expires_at=now()-interval '1 second' WHERE id=:id"), {"id": job_id})
        assert (await repository.claim("worker-b", payload_tag=tag)).id == job_id  # type: ignore[union-attr]
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM jobs WHERE id=:id"), {"id": job_id})
        await engine.dispose()


@pytest.mark.asyncio
async def test_transient_retry_backoff_and_sanitized_poison_failure(disposable_worker_database: str) -> None:
    engine = create_async_engine(disposable_worker_database)
    repository = JobRepository(engine, lease_duration=timedelta(seconds=2), max_attempts=2)
    tag = uuid4().hex
    retry_id = await repository.enqueue({"retry": True, "_queue_tag": tag})
    poison_id = await repository.enqueue({"poison": True, "_queue_tag": tag})
    attempts = 0

    async def flaky(_job: Job, _context: ExecutionContext) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("mongodb://user:SUPER_SECRET_CANARY@example Authorization: Bearer SUPER_SECRET_TOKEN")

    async def poison(_job: Job, _context: ExecutionContext) -> None:
        raise PermanentJobError("FORBIDDEN_CONFIGURATION")

    try:
        worker = DurableJobWorker(repository, "worker-a", payload_tag=tag)
        assert await worker.run_once(flaky)
        first = await _status(engine, retry_id)
        assert first["status"] == "PENDING" and first["attempts"] == 1 and first["last_error_code"] == "RuntimeError"
        assert await repository.claim("worker-b", payload_tag=tag) is not None  # claims poison, retry is unavailable
        await repository.fail(Job(poison_id, None, "OPTIMIZATION", {"poison": True, "_queue_tag": tag}, 1), "worker-b", "FORBIDDEN_CONFIGURATION", permanent=True)
        await asyncio.sleep(1.1)
        assert await worker.run_once(flaky)
        second = await _status(engine, retry_id)
        assert second["status"] == "COMPLETED" and second["attempts"] == 2
        failed = await _status(engine, poison_id)
        assert failed["status"] == "FAILED" and failed["failed_at"] is not None and failed["last_error_code"] == "FORBIDDEN_CONFIGURATION"
        assert "SUPER_SECRET" not in str(first)
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM jobs WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": [retry_id, poison_id]})
        await engine.dispose()


@pytest.mark.asyncio
async def test_transient_poison_stops_at_max_attempts(disposable_worker_database: str) -> None:
    engine = create_async_engine(disposable_worker_database)
    repository = JobRepository(engine, max_attempts=2)
    tag = uuid4().hex
    job_id = await repository.enqueue({"max_attempts": True, "_queue_tag": tag})

    async def always_transient(_job: Job, _context: ExecutionContext) -> None:
        raise TimeoutError("temporary")

    try:
        worker = DurableJobWorker(repository, "worker-a", payload_tag=tag)
        await worker.run_once(always_transient)
        assert (await _status(engine, job_id))["status"] == "PENDING"
        await asyncio.sleep(1.1)
        await worker.run_once(always_transient)
        state = await _status(engine, job_id)
        assert state["status"] == "FAILED" and state["attempts"] == 2 and state["failed_at"] is not None
        assert await repository.claim("worker-b", payload_tag=tag) is None
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM jobs WHERE id=:id"), {"id": job_id})
        await engine.dispose()
