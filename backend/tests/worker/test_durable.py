"""Phase 26 integration acceptance tests for the durable PostgreSQL worker."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.worker.durable import DurableJobWorker, Job, JobRepository


DATABASE_URL = "postgresql+asyncpg://control_plane:control_plane_dev_only@127.0.0.1:5432/control_plane"


@pytest_asyncio.fixture
async def job_repository() -> AsyncIterator[JobRepository]:
    engine = create_async_engine(DATABASE_URL)
    repository = JobRepository(engine, lease_duration=timedelta(seconds=1))
    job_ids: list[str] = []
    try:
        for number in range(100):
            job_ids.append(await repository.enqueue({"number": number}))
        yield repository
    finally:
        if job_ids:
            async with engine.begin() as connection:
                await connection.execute(text("DELETE FROM jobs WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": job_ids})
        await engine.dispose()


@pytest.mark.asyncio
async def test_two_workers_execute_one_hundred_jobs_exactly_once(job_repository: JobRepository) -> None:
    executed: list[str] = []

    async def handler(job: Job) -> None:
        await asyncio.sleep(0)
        executed.append(job.id)

    first = DurableJobWorker(job_repository, "worker-a")
    second = DurableJobWorker(job_repository, "worker-b")
    counts = await asyncio.gather(first.run_until_idle(handler), second.run_until_idle(handler))

    assert sum(counts) == 100
    assert len(executed) == 100
    assert len(set(executed)) == 100


@pytest.mark.asyncio
async def test_expired_lease_is_recovered_by_another_worker() -> None:
    engine: AsyncEngine = create_async_engine(DATABASE_URL)
    repository = JobRepository(engine, lease_duration=timedelta(milliseconds=-1))
    job_id = await repository.enqueue({"recovery": True})
    try:
        claimed = await repository.claim("crashed-worker")
        recovered = await repository.claim("recovery-worker")

        assert claimed is not None
        assert recovered is not None
        assert recovered.id == job_id
        assert recovered.attempts == 2
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": job_id})
        await engine.dispose()
