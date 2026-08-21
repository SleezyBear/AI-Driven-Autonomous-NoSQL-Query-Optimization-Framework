"""PostgreSQL-backed durable job claiming with leases and heartbeats."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.resources.protection import HeavyTaskKind, HeavyTaskLimiter, shared_heavy_task_limiter


T = TypeVar("T")


@dataclass(frozen=True)
class Job:
    """A claimed durable job whose lease belongs to one worker."""

    id: str
    payload: Mapping[str, Any]
    attempts: int


class JobRepository:
    """Persist jobs and atomically claim them with PostgreSQL row locks."""

    def __init__(self, engine: AsyncEngine, lease_duration: timedelta = timedelta(seconds=30)) -> None:
        self._engine = engine
        self._lease_duration = lease_duration

    async def enqueue(self, payload: Mapping[str, Any]) -> str:
        """Persist one pending job and return its durable identifier."""
        job_id = str(uuid4())
        now = datetime.now(timezone.utc)
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO jobs (id, created_at, updated_at, payload, status, attempts) "
                    "VALUES (:id, :now, :now, CAST(:payload AS jsonb), 'PENDING', 0)"
                ),
                {"id": job_id, "now": now, "payload": json.dumps(dict(payload), sort_keys=True)},
            )
        return job_id

    async def claim(self, worker_id: str) -> Job | None:
        """Atomically lease one pending or expired job using SKIP LOCKED."""
        now = datetime.now(timezone.utc)
        expires_at = now + self._lease_duration
        statement = text(
            "WITH claimable AS ("
            " SELECT id FROM jobs"
            " WHERE status = 'PENDING' OR (status = 'RUNNING' AND lease_expires_at <= :now)"
            " ORDER BY created_at, id"
            " FOR UPDATE SKIP LOCKED"
            " LIMIT 1"
            ")"
            " UPDATE jobs AS job"
            " SET status = 'RUNNING', lease_owner = :worker_id, lease_expires_at = :expires_at,"
            " heartbeat_at = :now, updated_at = :now, attempts = attempts + 1"
            " FROM claimable"
            " WHERE job.id = claimable.id"
            " RETURNING job.id, job.payload, job.attempts"
        )
        async with self._engine.begin() as connection:
            row = (await connection.execute(statement, {"worker_id": worker_id, "now": now, "expires_at": expires_at})).mappings().one_or_none()
        if row is None:
            return None
        return Job(id=str(row["id"]), payload=row["payload"], attempts=row["attempts"])

    async def heartbeat(self, job_id: str, worker_id: str) -> bool:
        """Extend a worker's current lease; a lost lease cannot be renewed."""
        now = datetime.now(timezone.utc)
        async with self._engine.begin() as connection:
            result = await connection.execute(
                text(
                    "UPDATE jobs SET heartbeat_at = :now, lease_expires_at = :expires_at, updated_at = :now "
                    "WHERE id = :id AND status = 'RUNNING' AND lease_owner = :worker_id AND lease_expires_at > :now"
                ),
                {"id": job_id, "worker_id": worker_id, "now": now, "expires_at": now + self._lease_duration},
            )
        return bool(result.rowcount == 1)

    async def complete(self, job_id: str, worker_id: str) -> bool:
        """Complete only a job still leased by the calling worker."""
        now = datetime.now(timezone.utc)
        async with self._engine.begin() as connection:
            result = await connection.execute(
                text(
                    "UPDATE jobs SET status = 'COMPLETED', completed_at = :now, updated_at = :now, "
                    "lease_owner = NULL, lease_expires_at = NULL "
                    "WHERE id = :id AND status = 'RUNNING' AND lease_owner = :worker_id"
                ),
                {"id": job_id, "worker_id": worker_id, "now": now},
            )
        return bool(result.rowcount == 1)


JobHandler = Callable[[Job], Awaitable[None]]


class DurableJobWorker:
    """Execute each successfully completed claim once while holding its database lease."""

    def __init__(self, repository: JobRepository, worker_id: str, heavy_task_limiter: HeavyTaskLimiter = shared_heavy_task_limiter) -> None:
        self._repository = repository
        self._worker_id = worker_id
        self._heavy_task_limiter = heavy_task_limiter

    async def run_heavy_task(self, kind: HeavyTaskKind, operation: Callable[[], Awaitable[T]], target_id: str | None = None) -> T:
        """Run expensive worker work under the Intel-safe concurrency limits."""
        return await self._heavy_task_limiter.run(kind, operation, target_id)

    async def run_once(self, handler: JobHandler) -> bool:
        """Claim, execute, and complete one job; return false when no job is claimable."""
        job = await self._repository.claim(self._worker_id)
        if job is None:
            return False
        await handler(job)
        if not await self._repository.complete(job.id, self._worker_id):
            raise RuntimeError(f"job lease lost before completion: {job.id}")
        return True

    async def run_until_idle(self, handler: JobHandler) -> int:
        """Run jobs until this worker cannot atomically claim another one."""
        completed = 0
        while await self.run_once(handler):
            completed += 1
        return completed
