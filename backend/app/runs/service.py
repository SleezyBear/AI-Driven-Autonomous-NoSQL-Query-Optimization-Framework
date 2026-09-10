"""Atomic persisted run and initial durable-job creation."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine

from app.autonomy.policy import DeploymentMode
from app.db.repositories import RunRepository
from app.worker.durable import JobRepository
from app.worker.durable import JobKind


@dataclass(frozen=True)
class CreatedOptimizationRun:
    run: RowMapping
    job_id: str


class OptimizationRunCreationService:
    """Create a CREATED run and its sole initial OPTIMIZATION job atomically."""

    def __init__(self, engine: AsyncEngine, jobs: JobRepository | None = None) -> None:
        self._engine = engine
        self._runs = RunRepository(engine)
        self._jobs = jobs or JobRepository(engine)

    async def create_run_with_initial_job(self, *, target_id: UUID, requested_by_user_id: UUID, deployment_mode: DeploymentMode, primary_metric_key: str | None) -> CreatedOptimizationRun:
        async with self._engine.begin() as connection:
            run = await self._runs.create_in_transaction(
                connection,
                target_id=target_id,
                workload_snapshot_id=None,
                status="CREATED",
                requested_by_user_id=requested_by_user_id,
                deployment_mode=deployment_mode.value,
                primary_metric_key=primary_metric_key,
            )
            job_id = await self._jobs.enqueue(
                {"run_id": str(run["id"]), "target_id": str(target_id)},
                optimization_run_id=str(run["id"]),
                kind=JobKind.OPTIMIZATION,
                connection=connection,
            )
            return CreatedOptimizationRun(run=run, job_id=job_id)
