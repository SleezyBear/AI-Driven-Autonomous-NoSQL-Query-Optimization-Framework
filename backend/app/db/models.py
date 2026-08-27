"""Relational models for the durable optimizer control plane."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer, JSON, LargeBinary, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]


class Base(DeclarativeBase):
    """Base for all control-plane mappings."""


class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CandidateStatus(str, Enum):
    PROPOSED = "PROPOSED"
    EVALUATING = "EVALUATING"
    ADMITTED = "ADMITTED"
    REJECTED = "REJECTED"


class TimestampedUUID(Base):
    """Common UUID identity and timestamps for durable entities."""

    __abstract__ = True
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())


class User(TimestampedUUID):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32), default="VIEWER")
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(TimestampedUUID):
    """One-time refresh-token record; only a SHA-256 digest is retained."""

    __tablename__ = "refresh_tokens"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Target(TimestampedUUID):
    __tablename__ = "targets"
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    deployment_mode: Mapped[str] = mapped_column(String(32), default="APPROVAL_CONTROLLED")
    state: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    connection_label: Mapped[str] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("owner_user_id", "name", name="uq_targets_owner_name"),)


class TargetCredential(TimestampedUUID):
    __tablename__ = "target_credentials"
    target_id: Mapped[UUID] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), unique=True)
    encrypted_payload: Mapped[bytes] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(Integer)
    credential_type: Mapped[str] = mapped_column(String(64))


class EvaluationMapping(TimestampedUUID):
    __tablename__ = "evaluation_mappings"
    target_id: Mapped[UUID] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), unique=True)
    evaluation_target_id: Mapped[UUID] = mapped_column(ForeignKey("targets.id", ondelete="RESTRICT"))
    mapping_status: Mapped[str] = mapped_column(String(32), default="ACTIVE")


class CapabilitySnapshot(TimestampedUUID):
    __tablename__ = "capability_snapshots"
    target_id: Mapped[UUID] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), index=True)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(128))


class Namespace(TimestampedUUID):
    __tablename__ = "namespaces"
    target_id: Mapped[UUID] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(256))
    allowlisted: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("target_id", "name", name="uq_namespaces_target_name"),)


class QueryShape(TimestampedUUID):
    __tablename__ = "query_shapes"
    namespace_id: Mapped[UUID] = mapped_column(ForeignKey("namespaces.id", ondelete="CASCADE"))
    shape_hash: Mapped[str] = mapped_column(String(128))
    normalized_shape: Mapped[dict[str, Any]] = mapped_column(JSON)
    operation: Mapped[str] = mapped_column(String(32))
    __table_args__ = (UniqueConstraint("namespace_id", "shape_hash", name="uq_query_shapes_namespace_hash"),)


class TelemetryWindow(TimestampedUUID):
    __tablename__ = "telemetry_windows"
    target_id: Mapped[UUID] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))


class MetricObservation(TimestampedUUID):
    __tablename__ = "metric_observations"
    telemetry_window_id: Mapped[UUID] = mapped_column(ForeignKey("telemetry_windows.id", ondelete="CASCADE"), index=True)
    query_shape_id: Mapped[UUID | None] = mapped_column(ForeignKey("query_shapes.id", ondelete="SET NULL"))
    metric_name: Mapped[str] = mapped_column(String(64))
    metric_value: Mapped[float] = mapped_column(Numeric)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkloadSnapshot(TimestampedUUID):
    __tablename__ = "workload_snapshots"
    target_id: Mapped[UUID] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"))
    telemetry_window_id: Mapped[UUID] = mapped_column(ForeignKey("telemetry_windows.id", ondelete="RESTRICT"))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(128), unique=True)


class OptimizationRun(TimestampedUUID):
    __tablename__ = "optimization_runs"
    target_id: Mapped[UUID] = mapped_column(ForeignKey("targets.id", ondelete="RESTRICT"), index=True)
    workload_snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("workload_snapshots.id", ondelete="RESTRICT"))
    status: Mapped[RunStatus] = mapped_column(SAEnum(RunStatus, name="run_status"), default=RunStatus.PENDING)
    requested_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class Candidate(TimestampedUUID):
    __tablename__ = "candidates"
    optimization_run_id: Mapped[UUID] = mapped_column(ForeignKey("optimization_runs.id", ondelete="CASCADE"), index=True)
    query_shape_id: Mapped[UUID] = mapped_column(ForeignKey("query_shapes.id", ondelete="RESTRICT"))
    status: Mapped[CandidateStatus] = mapped_column(SAEnum(CandidateStatus, name="candidate_status"), default=CandidateStatus.PROPOSED)
    candidate_hash: Mapped[str] = mapped_column(String(128), unique=True)


class CandidateAction(TimestampedUUID):
    __tablename__ = "candidate_actions"
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    action_type: Mapped[str] = mapped_column(String(64))
    action_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    reversible: Mapped[bool] = mapped_column(Boolean, default=True)


class EvaluationRun(TimestampedUUID):
    __tablename__ = "evaluation_runs"
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    environment_fingerprint: Mapped[str] = mapped_column(String(128))


class TrialPair(TimestampedUUID):
    __tablename__ = "trial_pairs"
    evaluation_run_id: Mapped[UUID] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True)
    pair_number: Mapped[int] = mapped_column(Integer)
    baseline_measurement: Mapped[dict[str, Any]] = mapped_column(JSON)
    candidate_measurement: Mapped[dict[str, Any]] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("evaluation_run_id", "pair_number", name="uq_trial_pairs_run_number"),)


class TrialMetric(TimestampedUUID):
    __tablename__ = "trial_metrics"
    trial_pair_id: Mapped[UUID] = mapped_column(ForeignKey("trial_pairs.id", ondelete="CASCADE"), index=True)
    metric_name: Mapped[str] = mapped_column(String(64))
    baseline_value: Mapped[float] = mapped_column(Numeric)
    candidate_value: Mapped[float] = mapped_column(Numeric)


class AdmissionDecision(TimestampedUUID):
    __tablename__ = "admission_decisions"
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id", ondelete="RESTRICT"), unique=True)
    verdict: Mapped[str] = mapped_column(String(32))
    evidence_hash: Mapped[str] = mapped_column(String(128))


class SafetyResult(TimestampedUUID):
    __tablename__ = "safety_results"
    admission_decision_id: Mapped[UUID] = mapped_column(ForeignKey("admission_decisions.id", ondelete="CASCADE"), index=True)
    check_name: Mapped[str] = mapped_column(String(64))
    verdict: Mapped[str] = mapped_column(String(32))
    details: Mapped[dict[str, Any]] = mapped_column(JSON)


class ApprovalRequest(TimestampedUUID):
    __tablename__ = "approval_requests"
    admission_decision_id: Mapped[UUID | None] = mapped_column(ForeignKey("admission_decisions.id", ondelete="RESTRICT"), unique=True)
    requested_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    action_id: Mapped[str] = mapped_column(String(128), index=True)
    target_id: Mapped[UUID] = mapped_column(ForeignKey("targets.id", ondelete="RESTRICT"), index=True)
    candidate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), index=True)
    evidence_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(32))


class ApprovalDecision(TimestampedUUID):
    __tablename__ = "approval_decisions"
    approval_request_id: Mapped[UUID] = mapped_column(ForeignKey("approval_requests.id", ondelete="CASCADE"), unique=True)
    decided_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decision: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text)


class LedgerEntry(TimestampedUUID):
    __tablename__ = "ledger_entries"
    optimization_run_id: Mapped[UUID] = mapped_column(ForeignKey("optimization_runs.id", ondelete="RESTRICT"), index=True)
    candidate_id: Mapped[UUID | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"))
    sequence_number: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(128))
    __table_args__ = (UniqueConstraint("optimization_run_id", "sequence_number", name="uq_ledger_run_sequence"),)


class RollbackRecord(TimestampedUUID):
    __tablename__ = "rollback_records"
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id", ondelete="RESTRICT"), unique=True)
    status: Mapped[str] = mapped_column(String(32))
    rollback_payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ExperienceRecord(TimestampedUUID):
    __tablename__ = "experience_records"
    candidate_id: Mapped[UUID | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"))
    outcome: Mapped[str | None] = mapped_column(String(64))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    adapter_type: Mapped[str] = mapped_column(String(64), default="mongodb")
    action_type: Mapped[str] = mapped_column(String(64), index=True, default="CREATE_INDEX")
    query_structure_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    workload_features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    bottleneck: Mapped[str | None] = mapped_column(String(128))
    candidate_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    prediction: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    admission_outcome: Mapped[str | None] = mapped_column(String(64))
    actual_postdeploy_outcome: Mapped[str | None] = mapped_column(String(64))
    rollback_outcome: Mapped[str | None] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(128), default="embeddinggemma")
    embedding_model_version: Mapped[str] = mapped_column(String(128), default="unknown")


class Job(TimestampedUUID):
    __tablename__ = "jobs"
    optimization_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("optimization_runs.id", ondelete="SET NULL"), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(64), default="OPTIMIZATION")


class AuditEvent(TimestampedUUID):
    __tablename__ = "audit_events"
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    optimization_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("optimization_runs.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(64))
    event_payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class Setting(TimestampedUUID):
    __tablename__ = "settings"
    scope: Mapped[str] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(128))
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("scope", "key", name="uq_settings_scope_key"),)
