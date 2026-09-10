"""Persisted, lease-aware OptimizationRun orchestration up to real boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.autonomy.policy import DeploymentMode
from app.diagnosis.durable import DiagnosisService, DiagnosisServiceError
from app.db import models
from app.db.repositories import ControlPlaneRepositories, RunRepository, create_repositories
from app.worker.durable import ExecutionContext
from app.workloads.durable import WorkloadSnapshotError, WorkloadSnapshotService


class OrchestrationOutcome(str, Enum):
    PROGRESSED = "PROGRESSED"
    BLOCKED = "BLOCKED"
    TERMINAL = "TERMINAL"


@dataclass(frozen=True)
class OrchestrationResult:
    """Typed result of one persisted orchestration resume attempt."""

    outcome: OrchestrationOutcome
    status: models.RunStatus
    blocker: str | None = None


class OrchestrationInvariantError(ValueError):
    """Persisted run data cannot safely enter the next lifecycle boundary."""


class OptimizationRunOrchestrator:
    """Resume only the real durable prefix of the OptimizationRun lifecycle."""

    def __init__(self, engine: AsyncEngine, repositories: ControlPlaneRepositories | None = None, snapshot_service: WorkloadSnapshotService | None = None, diagnosis_service: DiagnosisService | None = None) -> None:
        self._engine = engine
        self._repositories = repositories or create_repositories(engine)
        self._runs = RunRepository(engine)
        self._snapshots = snapshot_service or WorkloadSnapshotService(engine)
        self._diagnosis = diagnosis_service

    async def run(self, run_id: UUID, execution_context: ExecutionContext) -> OrchestrationResult:
        """Reload authoritative state and advance no further than durable capability permits."""
        execution_context.ensure_lease_owned()
        run = await self._runs.get(run_id)
        if run is None:
            raise OrchestrationInvariantError("optimization run does not exist")
        status = _run_status(run["status"])
        if status in _TERMINAL:
            return OrchestrationResult(OrchestrationOutcome.TERMINAL, status)
        if status is models.RunStatus.SNAPSHOTTING:
            try:
                if run["workload_snapshot_id"] is None:
                    execution_context.ensure_lease_owned()
                    await self._snapshots.create_for_run(run_id)
                refreshed = await self._runs.get(run_id)
                if refreshed is None or refreshed["workload_snapshot_id"] is None:
                    raise OrchestrationInvariantError("snapshot service did not attach a workload snapshot")
                if not await self._snapshots.verify_snapshot_integrity(refreshed["workload_snapshot_id"]):
                    raise OrchestrationInvariantError("workload snapshot integrity verification failed")
                execution_context.ensure_lease_owned()
                transitioned = await self._runs.transition(run_id, models.RunStatus.DIAGNOSING)
                return OrchestrationResult(OrchestrationOutcome.PROGRESSED, _run_status(transitioned["status"]))
            except WorkloadSnapshotError as error:
                return OrchestrationResult(OrchestrationOutcome.BLOCKED, status, error.code.value)
        if status is models.RunStatus.DIAGNOSING:
            if self._diagnosis is None:
                return OrchestrationResult(OrchestrationOutcome.BLOCKED, status, "DIAGNOSIS_SERVICE_UNAVAILABLE")
            try:
                execution_context.ensure_lease_owned()
                diagnosis = await self._diagnosis.create_for_run(run_id)
                if not await self._diagnosis.verify_diagnosis_integrity(diagnosis.diagnosis_id):
                    raise OrchestrationInvariantError("diagnosis integrity verification failed")
                execution_context.ensure_lease_owned()
                transitioned = await self._runs.transition(run_id, models.RunStatus.GENERATING_CANDIDATES)
                return OrchestrationResult(OrchestrationOutcome.PROGRESSED, _run_status(transitioned["status"]))
            except DiagnosisServiceError as error:
                return OrchestrationResult(OrchestrationOutcome.BLOCKED, status, error.code.value)
        if status is not models.RunStatus.CREATED:
            raise OrchestrationInvariantError(f"unsupported durable orchestration resume state: {status.value}")

        await self._validate_created(run_id, run)
        execution_context.ensure_lease_owned()
        transitioned = await self._runs.transition(run_id, models.RunStatus.SNAPSHOTTING)
        return OrchestrationResult(OrchestrationOutcome.PROGRESSED, _run_status(transitioned["status"]))

    async def _validate_created(self, run_id: UUID, run: object) -> None:
        """Validate only persisted facts required before starting snapshot work."""
        target_id = run["target_id"]  # type: ignore[index]
        try:
            DeploymentMode(str(run["deployment_mode"]))  # type: ignore[index]
        except ValueError as error:
            raise OrchestrationInvariantError("run deployment mode is invalid") from error
        target = await self._repositories.targets.get(target_id)
        if target is None or not target["is_active"] or target["state"] != "ACTIVE":
            raise OrchestrationInvariantError("run target is not active")
        async with self._engine.connect() as connection:
            mapping = (
                await connection.execute(
                    select(models.EvaluationMapping.__table__).where(
                        models.EvaluationMapping.__table__.c.target_id == target_id,
                        models.EvaluationMapping.__table__.c.mapping_status == "ACTIVE",
                    )
                )
            ).mappings().one_or_none()
            job_count = (
                await connection.execute(
                    select(models.Job.__table__.c.id).where(
                        models.Job.__table__.c.optimization_run_id == run_id,
                        models.Job.__table__.c.kind == "OPTIMIZATION",
                    )
                )
            ).all()
        if mapping is None or mapping["evaluation_target_id"] == target_id:
            raise OrchestrationInvariantError("run has no valid distinct evaluation target")
        evaluation_target = await self._repositories.targets.get(mapping["evaluation_target_id"])
        if evaluation_target is None or not evaluation_target["is_active"] or evaluation_target["state"] != "ACTIVE":
            raise OrchestrationInvariantError("evaluation target is not active")
        if len(job_count) != 1:
            raise OrchestrationInvariantError("run must have exactly one authoritative initial optimization job")


_TERMINAL = frozenset({models.RunStatus.COMPLETED, models.RunStatus.ROLLED_BACK, models.RunStatus.ROLLBACK_BLOCKED, models.RunStatus.FAILED})


def _run_status(value: object) -> models.RunStatus:
    return value if isinstance(value, models.RunStatus) else models.RunStatus(str(value))
