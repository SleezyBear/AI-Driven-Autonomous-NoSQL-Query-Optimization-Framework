"""R19C worker polling, shutdown, readiness, and outage recovery coverage."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from time import monotonic
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.worker.durable import DurableJobWorker, ExecutionContext, Job, JobRepository, LeaseLostError
from app.worker.service import WorkerService, readiness


class _HandlerDispatcher:
    def __init__(self, handler: Any) -> None:
        self._handler = handler

    async def dispatch(self, job: Job, context: ExecutionContext) -> None:
        await self._handler(job, context)


@pytest.mark.asyncio
async def test_real_idle_worker_polls_at_interval_and_stops_cleanly(disposable_worker_database: str) -> None:
    engine = create_async_engine(disposable_worker_database)
    repository = JobRepository(engine)
    durable = DurableJobWorker(repository, "idle-worker")
    calls: list[float] = []
    original = durable.run_once

    async def recorded(handler: Any, *, stopping: asyncio.Event | None = None) -> bool:
        calls.append(monotonic())
        return await original(handler, stopping=stopping)

    durable.run_once = recorded  # type: ignore[method-assign]

    async def handler(_job: Job, _context: ExecutionContext) -> None:
        raise AssertionError("an idle worker must not invoke a handler")

    stopping = asyncio.Event()
    service = WorkerService(durable, _HandlerDispatcher(handler), poll_interval=0.12, identity="idle-worker")
    try:
        task = asyncio.create_task(service.run(stopping))
        # Observe at least two real idle polls before stopping.  Waiting for the
        # expected number of polls (bounded by a generous deadline) keeps the
        # assertion strict while tolerating slow Postgres round-trips under load.
        deadline = monotonic() + 3
        while len(calls) < 2 and monotonic() < deadline:
            await asyncio.sleep(0.02)
        stopping.set()
        await asyncio.wait_for(task, timeout=2)
        assert not service.live
        assert len(calls) >= 2
        assert all(later - earlier >= 0.08 for earlier, later in zip(calls, calls[1:]))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_graceful_active_shutdown_keeps_real_job_recoverable(disposable_worker_database: str) -> None:
    engine = create_async_engine(disposable_worker_database)
    repository = JobRepository(engine, lease_duration=timedelta(milliseconds=180))
    job_id = await repository.enqueue({"active_shutdown": True})
    entered = asyncio.Event()

    async def long_running(_job: Job, context: ExecutionContext) -> None:
        entered.set()
        while not context.lease_lost.is_set():
            await asyncio.sleep(0.01)
        with pytest.raises(LeaseLostError):
            context.ensure_lease_owned()
        raise LeaseLostError("shutdown leaves the job for durable recovery")

    stopping = asyncio.Event()
    service = WorkerService(
        DurableJobWorker(repository, "shutdown-worker-a"),
        _HandlerDispatcher(long_running),
        poll_interval=0.05,
        identity="shutdown-worker-a",
    )
    try:
        task = asyncio.create_task(service.run(stopping))
        await asyncio.wait_for(entered.wait(), timeout=1)
        stopping.set()
        await asyncio.wait_for(task, timeout=1)
        async with engine.connect() as connection:
            status = (await connection.execute(text("SELECT status FROM jobs WHERE id=:id"), {"id": job_id})).scalar_one()
        assert status == "RUNNING"
        await asyncio.sleep(0.22)
        recovered = await repository.claim("shutdown-worker-b")
        assert recovered is not None and recovered.id == job_id and recovered.attempts == 2
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM jobs WHERE id=:id"), {"id": job_id})
        await engine.dispose()


@pytest.mark.asyncio
async def test_readiness_tracks_real_postgres_availability(disposable_worker_database: str) -> None:
    engine = create_async_engine(disposable_worker_database)
    unavailable = create_async_engine("postgresql+asyncpg://user:OUTAGE_SECRET@127.0.0.1:1/missing", connect_args={"timeout": 0.1})
    try:
        assert await readiness(JobRepository(engine))
        assert not await readiness(JobRepository(unavailable))
    finally:
        await unavailable.dispose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_outage_is_sanitized_and_real_polling_recovers(
    monkeypatch: pytest.MonkeyPatch, disposable_worker_database: str
) -> None:
    engine = create_async_engine(disposable_worker_database)
    repository = JobRepository(engine)
    job_id = await repository.enqueue({"outage_recovery": True})
    real_worker = DurableJobWorker(repository, "outage-worker")
    events: list[dict[str, object]] = []

    class FailsOnce:
        def __init__(self) -> None:
            self.failed = False

        async def run_once(self, handler: Any, *, stopping: asyncio.Event | None = None) -> bool:
            if not self.failed:
                self.failed = True
                raise OSError("postgresql://user:OUTAGE_SECRET@db.example/control")
            return await real_worker.run_once(handler, stopping=stopping)

    class Recorder:
        def warning(self, event: str, **fields: object) -> None:
            events.append({"event": event, **fields})

        def info(self, _event: str, **_fields: object) -> None:
            return None

    async def complete(_job: Job, _context: ExecutionContext) -> None:
        return None

    from app.worker import service as service_module

    monkeypatch.setattr(service_module, "_log", Recorder())
    stopping = asyncio.Event()
    service = WorkerService(FailsOnce(), _HandlerDispatcher(complete), poll_interval=0.05, identity="outage-worker")  # type: ignore[arg-type]
    try:
        task = asyncio.create_task(service.run(stopping))
        for _ in range(30):
            async with engine.connect() as connection:
                status = (await connection.execute(text("SELECT status FROM jobs WHERE id=:id"), {"id": job_id})).scalar_one()
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.03)
        stopping.set()
        await asyncio.wait_for(task, timeout=1)
        assert status == "COMPLETED"
        assert any(event["event"] == "worker_database_unavailable" for event in events)
        assert "OUTAGE_SECRET" not in str(events)
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM jobs WHERE id=:id"), {"id": job_id})
        await engine.dispose()
