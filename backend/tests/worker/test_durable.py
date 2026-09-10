"""Phase 26 integration acceptance tests for the durable PostgreSQL worker."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.worker.durable import DurableJobWorker, Job, JobRepository
from tests.support.disposable_postgres import migrated_worker_database


@pytest_asyncio.fixture
async def job_repository() -> AsyncIterator[JobRepository]:
    async with migrated_worker_database() as database_url:
        engine = create_async_engine(database_url)
        repository = JobRepository(engine, lease_duration=timedelta(seconds=1))
        tag = uuid4().hex
        try:
            job_ids = [await repository.enqueue({"number": number, "_queue_tag": tag}) for number in range(100)]
            yield repository, tag
            async with engine.connect() as connection:
                completed = (await connection.execute(text("SELECT count(*) FROM jobs WHERE id = ANY(CAST(:ids AS uuid[])) AND status='COMPLETED'"), {"ids": job_ids})).scalar_one()
            assert completed == 100
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_two_workers_execute_one_hundred_jobs_exactly_once(job_repository: tuple[JobRepository, str]) -> None:
    executed: list[str] = []

    async def handler(job: Job, _cancelled: asyncio.Event) -> None:
        await asyncio.sleep(0)
        executed.append(job.id)

    repository, tag = job_repository
    first = DurableJobWorker(repository, "worker-a", payload_tag=tag)
    second = DurableJobWorker(repository, "worker-b", payload_tag=tag)
    counts = await asyncio.gather(first.run_until_idle(handler), second.run_until_idle(handler))

    assert sum(counts) == 100
    assert len(executed) == 100
    assert len(set(executed)) == 100


@pytest.mark.asyncio
async def test_newly_enqueued_job_is_immediately_claimable(disposable_worker_database: str) -> None:
    """A committed ordinary job must be claimable by a separate connection immediately."""
    enqueue_engine = create_async_engine(disposable_worker_database)
    claim_engine = create_async_engine(disposable_worker_database)
    enqueue_repository = JobRepository(enqueue_engine)
    claim_repository = JobRepository(claim_engine)
    tag = uuid4().hex
    try:
        job_id = await enqueue_repository.enqueue({"immediate_claim": True, "_queue_tag": tag})
        claim_now = datetime.now(timezone.utc)
        async with claim_engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT id, status, kind, optimization_run_id, attempts, available_at, lease_owner, "
                        "lease_expires_at, created_at, updated_at, now() AS database_now, "
                        "current_setting('TimeZone') AS timezone, status = 'PENDING' AS status_is_claimable, "
                        "available_at <= :claim_now AS available_at_is_due, "
                        "(payload ->> '_queue_tag') = :tag AS payload_tag_matches "
                        "FROM jobs WHERE id = :id"
                    ),
                    {"id": job_id, "claim_now": claim_now, "tag": tag},
                )
            ).mappings().one()
        diagnostics = {
            "id": str(row["id"]),
            "status": row["status"],
            "kind": row["kind"],
            "optimization_run_id": row["optimization_run_id"],
            "attempts": row["attempts"],
            "max_attempts": claim_repository._max_attempts,
            "available_at": row["available_at"],
            "lease_owner": row["lease_owner"],
            "lease_expires_at": row["lease_expires_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "database_now": row["database_now"],
            "timezone": row["timezone"],
            "status_is_claimable": row["status_is_claimable"],
            "available_at_is_due": row["available_at_is_due"],
            "payload_tag_matches": row["payload_tag_matches"],
        }
        print(f"immediate_claim_diagnostics={diagnostics}")
        claimed = await claim_repository.claim("immediate-claim-worker", payload_tag=tag)
        assert claimed is not None
        assert claimed.id == job_id
    finally:
        await claim_engine.dispose()
        await enqueue_engine.dispose()


@pytest.mark.asyncio
async def test_expired_lease_is_recovered_by_another_worker(disposable_worker_database: str) -> None:
    engine = create_async_engine(disposable_worker_database)
    repository = JobRepository(engine, lease_duration=timedelta(milliseconds=-1))
    tag = uuid4().hex
    job_id = await repository.enqueue({"recovery": True, "_queue_tag": tag})
    try:
        claimed = await repository.claim("crashed-worker", payload_tag=tag)
        async with engine.connect() as connection:
            claimed_row = (
                await connection.execute(
                    text("SELECT status, lease_owner, attempts FROM jobs WHERE id=:id"), {"id": job_id}
                )
            ).mappings().one()
        assert claimed is not None, dict(claimed_row)
        assert claimed.id == job_id
        assert claimed_row["status"] == "RUNNING"
        assert claimed_row["lease_owner"] == "crashed-worker"
        recovered = await repository.claim("recovery-worker", payload_tag=tag)

        assert recovered is not None
        assert recovered.id == job_id
        assert recovered.attempts == 2
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": job_id})
        await engine.dispose()


@pytest.mark.asyncio
async def test_heartbeat_keeps_long_handler_owned_past_original_lease(disposable_worker_database: str) -> None:
    engine = create_async_engine(disposable_worker_database)
    repository = JobRepository(engine, lease_duration=timedelta(milliseconds=200))
    tag = uuid4().hex
    job_id = await repository.enqueue({"heartbeat": True, "_queue_tag": tag})
    handler_started = asyncio.Event()
    allow_completion = asyncio.Event()

    async def handler(job: Job, _cancelled: asyncio.Event) -> None:
        assert job.id == job_id
        handler_started.set()
        await allow_completion.wait()

    try:
        worker = DurableJobWorker(repository, "worker-a", payload_tag=tag)
        task = asyncio.create_task(worker.run_once(handler))
        await asyncio.wait_for(handler_started.wait(), timeout=1)
        async with engine.connect() as connection:
            initial = (
                await connection.execute(
                    text("SELECT lease_owner, lease_expires_at FROM jobs WHERE id=:id"), {"id": job_id}
                )
            ).mappings().one()
        assert initial["lease_owner"] == "worker-a"
        original_expiry = initial["lease_expires_at"]
        await asyncio.sleep(0.3)
        async with engine.connect() as connection:
            renewed = (
                await connection.execute(
                    text("SELECT lease_owner, lease_expires_at FROM jobs WHERE id=:id"), {"id": job_id}
                )
            ).mappings().one()
        assert renewed["lease_owner"] == "worker-a"
        assert renewed["lease_expires_at"] > original_expiry
        assert await repository.claim("worker-b", payload_tag=tag) is None
        allow_completion.set()
        assert await asyncio.wait_for(task, timeout=1)
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": job_id})
        await engine.dispose()
