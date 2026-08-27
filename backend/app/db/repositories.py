"""PostgreSQL repositories for every durable control-plane domain."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import Table, delete, insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import models


T = TypeVar("T", bound=models.TimestampedUUID)


class PostgresRepository(Generic[T]):
    """Small explicit persistence boundary backed by one SQLAlchemy table."""

    model: type[T]

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @property
    def table(self) -> Table:
        return self.model.__table__

    async def create(self, **values: Any) -> RowMapping:
        allowed = set(self.table.c.keys()) - {"id", "created_at", "updated_at"}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"unsupported {self.table.name} columns: {sorted(unknown)}")
        now = datetime.now(timezone.utc)
        payload = {"id": uuid4(), "created_at": now, "updated_at": now, **values}
        async with self._engine.begin() as connection:
            result = await connection.execute(insert(self.table).values(**payload).returning(*self.table.c))
            return result.mappings().one()

    async def get(self, record_id: str | UUID) -> RowMapping | None:
        async with self._engine.connect() as connection:
            result = await connection.execute(select(self.table).where(self.table.c.id == UUID(str(record_id))))
            return result.mappings().one_or_none()

    async def list(self) -> tuple[RowMapping, ...]:
        async with self._engine.connect() as connection:
            result = await connection.execute(select(self.table).order_by(self.table.c.created_at, self.table.c.id))
            return tuple(result.mappings().all())

    async def delete(self, record_id: str | UUID) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(delete(self.table).where(self.table.c.id == UUID(str(record_id))))


class UserRepository(PostgresRepository[models.User]):
    model = models.User


class TargetRepository(PostgresRepository[models.Target]):
    model = models.Target


class RunRepository(PostgresRepository[models.OptimizationRun]):
    model = models.OptimizationRun


class CandidateRepository(PostgresRepository[models.Candidate]):
    model = models.Candidate


class EvaluationRepository(PostgresRepository[models.EvaluationRun]):
    model = models.EvaluationRun


class AdmissionRepository(PostgresRepository[models.AdmissionDecision]):
    model = models.AdmissionDecision


class ApprovalRepository(PostgresRepository[models.ApprovalRequest]):
    model = models.ApprovalRequest

    async def decide(self, request_id: str | UUID, decided_by_user_id: str | UUID, decision: str, reason: str | None = None) -> RowMapping:
        decision_repository = ApprovalDecisionRepository(self._engine)
        return await decision_repository.create(
            approval_request_id=UUID(str(request_id)),
            decided_by_user_id=UUID(str(decided_by_user_id)),
            decision=decision,
            reason=reason,
        )


class ApprovalDecisionRepository(PostgresRepository[models.ApprovalDecision]):
    model = models.ApprovalDecision


class LedgerRepository(PostgresRepository[models.LedgerEntry]):
    model = models.LedgerEntry


class ExperienceRepository(PostgresRepository[models.ExperienceRecord]):
    model = models.ExperienceRecord


class JobRepository(PostgresRepository[models.Job]):
    model = models.Job


class AuditRepository(PostgresRepository[models.AuditEvent]):
    model = models.AuditEvent


class CredentialRepository(PostgresRepository[models.TargetCredential]):
    model = models.TargetCredential


class EvaluationMappingRepository(PostgresRepository[models.EvaluationMapping]):
    model = models.EvaluationMapping


class CapabilityRepository(PostgresRepository[models.CapabilitySnapshot]):
    model = models.CapabilitySnapshot


class NamespaceRepository(PostgresRepository[models.Namespace]):
    model = models.Namespace


class QueryShapeRepository(PostgresRepository[models.QueryShape]):
    model = models.QueryShape


class TelemetryRepository(PostgresRepository[models.TelemetryWindow]):
    model = models.TelemetryWindow


class MetricRepository(PostgresRepository[models.MetricObservation]):
    model = models.MetricObservation


class WorkloadRepository(PostgresRepository[models.WorkloadSnapshot]):
    model = models.WorkloadSnapshot


class CandidateActionRepository(PostgresRepository[models.CandidateAction]):
    model = models.CandidateAction


class TrialPairRepository(PostgresRepository[models.TrialPair]):
    model = models.TrialPair


class TrialMetricRepository(PostgresRepository[models.TrialMetric]):
    model = models.TrialMetric


class SafetyRepository(PostgresRepository[models.SafetyResult]):
    model = models.SafetyResult


class RollbackRepository(PostgresRepository[models.RollbackRecord]):
    model = models.RollbackRecord


class RecoveryRepository(AuditRepository):
    """Persistent recovery journal stored as append-only audit events."""

    async def checkpoint(self, event_type: str, event_payload: Mapping[str, Any]) -> RowMapping:
        return await self.create(actor_user_id=None, optimization_run_id=None, event_type=event_type, event_payload=dict(event_payload))


class SettingsRepository(PostgresRepository[models.Setting]):
    model = models.Setting


class ControlPlaneRepositories:
    """Application-owned collection of all PostgreSQL repository boundaries."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.users = UserRepository(engine)
        self.targets = TargetRepository(engine)
        self.credentials = CredentialRepository(engine)
        self.evaluation_mappings = EvaluationMappingRepository(engine)
        self.capabilities = CapabilityRepository(engine)
        self.namespaces = NamespaceRepository(engine)
        self.query_shapes = QueryShapeRepository(engine)
        self.telemetry = TelemetryRepository(engine)
        self.metrics = MetricRepository(engine)
        self.workloads = WorkloadRepository(engine)
        self.runs = RunRepository(engine)
        self.candidates = CandidateRepository(engine)
        self.candidate_actions = CandidateActionRepository(engine)
        self.evaluations = EvaluationRepository(engine)
        self.trial_pairs = TrialPairRepository(engine)
        self.trial_metrics = TrialMetricRepository(engine)
        self.admissions = AdmissionRepository(engine)
        self.safety = SafetyRepository(engine)
        self.approvals = ApprovalRepository(engine)
        self.ledger = LedgerRepository(engine)
        self.rollback = RollbackRepository(engine)
        self.experience = ExperienceRepository(engine)
        self.jobs = JobRepository(engine)
        self.audit = AuditRepository(engine)
        self.recovery = RecoveryRepository(engine)
        self.settings = SettingsRepository(engine)


def create_repositories(engine: AsyncEngine) -> ControlPlaneRepositories:
    """Build the production repository graph from an application engine."""
    return ControlPlaneRepositories(engine)
