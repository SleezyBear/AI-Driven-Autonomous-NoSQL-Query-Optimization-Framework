"""Persisted, lease-aware OptimizationRun orchestration up to real boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from collections.abc import Awaitable, Callable, Mapping
from uuid import UUID
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.admission.durable import DurableAdmissionService
from app.admission.models import AdmissionRequest, BenchmarkProfile
from app.autonomy.policy import DeploymentMode
from app.approvals.durable import DurableApprovalService
from app.authority.durable import DurableAuthorityService
from app.candidates.durable import CandidateGenerationError, CandidateGenerationService
from app.diagnosis.durable import DiagnosisService, DiagnosisServiceError
from app.db import models
from app.db.repositories import ControlPlaneRepositories, RunRepository, create_repositories
from app.evaluation.durable import DurableEvaluationService, EvaluationPlanError
from app.ranking.durable import CandidateRankingError, CandidateRankingService
from app.worker.durable import ExecutionContext
from app.workloads.durable import WorkloadSnapshotError, WorkloadSnapshotService
from app.monitoring.post_deployment import MonitoringResult, MonitoringStatus
from app.production.durable import DurableDeploymentService


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

    def __init__(self, engine: AsyncEngine, repositories: ControlPlaneRepositories | None = None, snapshot_service: WorkloadSnapshotService | None = None, diagnosis_service: DiagnosisService | None = None, candidate_service: CandidateGenerationService | None = None, ranking_service: CandidateRankingService | None = None, evaluation_service: DurableEvaluationService | None = None, admission_service: DurableAdmissionService | None = None, evaluation_executor: Callable[[UUID], Awaitable[None]] | None = None, admission_requests: Callable[[UUID], Awaitable[dict[UUID, AdmissionRequest]]] | None = None, authority_service: DurableAuthorityService | None = None, approval_service: DurableApprovalService | None = None, deployment_service: DurableDeploymentService | None = None, monitoring_executor: Callable[[UUID], Awaitable[MonitoringResult]] | None = None) -> None:
        self._engine = engine
        self._repositories = repositories or create_repositories(engine)
        self._runs = RunRepository(engine)
        self._snapshots = snapshot_service or WorkloadSnapshotService(engine)
        self._diagnosis = diagnosis_service
        self._candidates = candidate_service
        self._ranking = ranking_service
        self._evaluation = evaluation_service
        self._admission = admission_service
        self._evaluation_executor = evaluation_executor
        self._admission_requests = admission_requests
        self._authority = authority_service
        self._approvals = approval_service
        self._deployment = deployment_service
        self._monitoring_executor = monitoring_executor

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
        if status is models.RunStatus.GENERATING_CANDIDATES:
            if self._candidates is None:
                return OrchestrationResult(OrchestrationOutcome.BLOCKED, status, "CANDIDATE_GENERATION_SERVICE_UNAVAILABLE")
            try:
                execution_context.ensure_lease_owned()
                generated = await self._candidates.create_for_run(run_id)
                execution_context.ensure_lease_owned()
                if generated.candidate_count == 0:
                    transitioned = await self._runs.transition(run_id, models.RunStatus.COMPLETED, models.RunCompletionReason.NO_CANDIDATES)
                else:
                    transitioned = await self._runs.transition(run_id, models.RunStatus.RANKING)
                return OrchestrationResult(OrchestrationOutcome.PROGRESSED, _run_status(transitioned["status"]))
            except CandidateGenerationError as error:
                return OrchestrationResult(OrchestrationOutcome.BLOCKED, status, str(error))
        if status is models.RunStatus.RANKING:
            if self._ranking is None:
                return OrchestrationResult(OrchestrationOutcome.BLOCKED, status, "CANDIDATE_RANKING_SERVICE_UNAVAILABLE")
            try:
                execution_context.ensure_lease_owned()
                await self._ranking.create_for_run(run_id)
                execution_context.ensure_lease_owned()
                transitioned = await self._runs.transition(run_id, models.RunStatus.CALIBRATING)
                return OrchestrationResult(OrchestrationOutcome.PROGRESSED, _run_status(transitioned["status"]))
            except CandidateRankingError as error:
                return OrchestrationResult(OrchestrationOutcome.BLOCKED, status, str(error))
        if status is models.RunStatus.CALIBRATING:
            if self._evaluation is None:
                return OrchestrationResult(OrchestrationOutcome.BLOCKED, status, "EVALUATION_SERVICE_UNAVAILABLE")
            try:
                execution_context.ensure_lease_owned()
                # Selection is frozen before controlled benchmark execution. The
                # isolated executor records real A/A calibration evidence later.
                profile = (
                    BenchmarkProfile.AUTONOMOUS
                    if str(run["deployment_mode"]) == DeploymentMode.FULL_AUTONOMOUS.value
                    else BenchmarkProfile.SMOKE
                )
                await self._evaluation.create_plan_for_run(run_id, profile, {"aa_calibration_status": "PENDING_MEASUREMENT"})
                execution_context.ensure_lease_owned()
                transitioned = await self._runs.transition(run_id, models.RunStatus.EVALUATING)
                return OrchestrationResult(OrchestrationOutcome.PROGRESSED, _run_status(transitioned["status"]))
            except EvaluationPlanError as error:
                return OrchestrationResult(OrchestrationOutcome.BLOCKED, status, str(error))
        if status is models.RunStatus.EVALUATING:
            if self._evaluation_executor is None:
                # A worker is deliberately not wired in this macro-phase: only
                # an injected isolated benchmark executor may create pair evidence.
                return OrchestrationResult(OrchestrationOutcome.BLOCKED, status, "ISOLATED_BENCHMARK_EXECUTOR_REQUIRED")
            execution_context.ensure_lease_owned()
            await self._evaluation_executor(run_id)
            execution_context.ensure_lease_owned()
            transitioned = await self._runs.transition(run_id, models.RunStatus.ADMISSION)
            return OrchestrationResult(OrchestrationOutcome.PROGRESSED, _run_status(transitioned["status"]))
        if status is models.RunStatus.ADMISSION:
            if self._admission is None or self._admission_requests is None:
                return OrchestrationResult(OrchestrationOutcome.BLOCKED, status, "ADMISSION_SERVICE_UNAVAILABLE")
            execution_context.ensure_lease_owned()
            result = await self._admission.decide_for_run(run_id, await self._admission_requests(run_id))
            execution_context.ensure_lease_owned()
            if result.selected_candidate_id is None:
                transitioned = await self._runs.transition(run_id, models.RunStatus.COMPLETED, models.RunCompletionReason.NO_ADMITTED_CANDIDATE)
            else:
                transitioned = await self._runs.transition(run_id, models.RunStatus.ADMITTED)
            return OrchestrationResult(OrchestrationOutcome.PROGRESSED, _run_status(transitioned["status"]))
        if status is models.RunStatus.ADMITTED:
            if self._authority is None:
                return OrchestrationResult(OrchestrationOutcome.BLOCKED, status, "AUTHORITY_SERVICE_UNAVAILABLE")
            authority = await self._authority.decide_for_run(run_id)
            execution_context.ensure_lease_owned()
            if authority.automatic:
                transitioned = await self._runs.transition(run_id, models.RunStatus.APPROVED)
                return OrchestrationResult(OrchestrationOutcome.PROGRESSED, _run_status(transitioned["status"]))
            if self._approvals is None:
                return OrchestrationResult(OrchestrationOutcome.BLOCKED, status, "APPROVAL_SERVICE_UNAVAILABLE")
            await self._create_bound_approval(run, authority.decision)
            execution_context.ensure_lease_owned()
            transitioned = await self._runs.transition(run_id, models.RunStatus.APPROVAL_PENDING)
            return OrchestrationResult(OrchestrationOutcome.BLOCKED, _run_status(transitioned["status"]), "WAITING_FOR_APPROVAL")
        if status is models.RunStatus.APPROVAL_PENDING:
            return OrchestrationResult(OrchestrationOutcome.BLOCKED, status, "WAITING_FOR_APPROVAL")
        if status in {models.RunStatus.APPROVED, models.RunStatus.DEPLOYING}:
            if self._deployment is None:
                return OrchestrationResult(OrchestrationOutcome.BLOCKED, status, "DURABLE_DEPLOYMENT_SERVICE_UNAVAILABLE")
            await self._deployment.deploy_for_run(run_id, execution_context)
            refreshed = await self._runs.get(run_id)
            if refreshed is None:
                raise OrchestrationInvariantError("run disappeared after durable deployment")
            return OrchestrationResult(OrchestrationOutcome.PROGRESSED, _run_status(refreshed["status"]))
        if status is models.RunStatus.DEPLOYED:
            execution_context.ensure_lease_owned()
            transitioned = await self._runs.transition(run_id, models.RunStatus.MONITORING)
            return OrchestrationResult(OrchestrationOutcome.PROGRESSED, _run_status(transitioned["status"]))
        if status is models.RunStatus.MONITORING:
            if self._monitoring_executor is None:
                return OrchestrationResult(OrchestrationOutcome.BLOCKED, status, "MONITORING_EVIDENCE_UNAVAILABLE")
            monitoring_result = await self._monitoring_executor(run_id)
            execution_context.ensure_lease_owned()
            if monitoring_result.status in {MonitoringStatus.STABLE, MonitoringStatus.WORKLOAD_SHIFT_DETECTED}:
                transitioned = await self._runs.transition(run_id, models.RunStatus.COMPLETED, models.RunCompletionReason.DEPLOYMENT_SUCCEEDED)
            elif monitoring_result.status is MonitoringStatus.ROLLED_BACK:
                transitioned = await self._runs.transition(run_id, models.RunStatus.ROLLED_BACK)
            else:
                transitioned = await self._runs.transition(run_id, models.RunStatus.ROLLBACK_BLOCKED)
            return OrchestrationResult(OrchestrationOutcome.PROGRESSED, _run_status(transitioned["status"]))
        if status is not models.RunStatus.CREATED:
            raise OrchestrationInvariantError(f"unsupported durable orchestration resume state: {status.value}")

        await self._validate_created(run_id, run)
        execution_context.ensure_lease_owned()
        transitioned = await self._runs.transition(run_id, models.RunStatus.SNAPSHOTTING)
        return OrchestrationResult(OrchestrationOutcome.PROGRESSED, _run_status(transitioned["status"]))

    async def _create_bound_approval(self, run: Mapping[str, object], authority: Mapping[str, object]) -> None:
        assert self._approvals is not None
        async with self._engine.connect() as connection:
            action = (await connection.execute(select(models.CandidateAction.__table__).where(models.CandidateAction.__table__.c.candidate_id == authority["candidate_id"]))).mappings().one_or_none()
        if action is None:
            raise OrchestrationInvariantError("selected candidate has no typed action")
        await self._approvals.request(
            action_id=str(action["id"]), target_id=cast(UUID, run["target_id"]), candidate_id=cast(UUID, authority["candidate_id"]),
            candidate_fingerprint=str(authority["candidate_fingerprint"]), evidence_hash=str(authority["integrity_fingerprint"]),
            requester_id=cast(UUID, run["requested_by_user_id"]), optimization_run_id=cast(UUID, run["id"]),
        )

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
