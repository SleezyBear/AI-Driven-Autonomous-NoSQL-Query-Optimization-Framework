"""Immutable, run-scoped diagnosis materialization from workload snapshots."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.ai.provider import AIProvider, DiagnosisArtifactResult, DiagnosisFinding, ProviderError
from app.db import models
from app.workloads.durable import SnapshotRead, WorkloadSnapshotService


SCHEMA_VERSION = "r19f-diagnosis-v1"
PROMPT_VERSION = "v1"


class DiagnosisFailureCode(str, Enum):
    SNAPSHOT_MISSING = "SNAPSHOT_MISSING"
    SNAPSHOT_RUN_MISMATCH = "SNAPSHOT_RUN_MISMATCH"
    SNAPSHOT_TARGET_MISMATCH = "SNAPSHOT_TARGET_MISMATCH"
    SNAPSHOT_INTEGRITY_FAILURE = "SNAPSHOT_INTEGRITY_FAILURE"
    DIAGNOSIS_SCHEMA_INVALID = "DIAGNOSIS_SCHEMA_INVALID"
    UNKNOWN_QUERY_SHAPE_REFERENCE = "UNKNOWN_QUERY_SHAPE_REFERENCE"
    UNKNOWN_EVIDENCE_REFERENCE = "UNKNOWN_EVIDENCE_REFERENCE"
    DIAGNOSIS_INTEGRITY_FAILURE = "DIAGNOSIS_INTEGRITY_FAILURE"
    PRIVACY_INVARIANT_FAILURE = "PRIVACY_INVARIANT_FAILURE"
    AI_PROVIDER_UNAVAILABLE = "AI_PROVIDER_UNAVAILABLE"
    AI_PROVIDER_TIMEOUT = "AI_PROVIDER_TIMEOUT"
    AI_PROVIDER_HTTP_ERROR = "AI_PROVIDER_HTTP_ERROR"
    AI_STRUCTURED_OUTPUT_UNSUPPORTED = "AI_STRUCTURED_OUTPUT_UNSUPPORTED"
    AI_RESPONSE_SCHEMA_INVALID = "AI_RESPONSE_SCHEMA_INVALID"


class DiagnosisServiceError(RuntimeError):
    def __init__(self, code: DiagnosisFailureCode, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code.value)


@dataclass(frozen=True)
class DiagnosisArtifactRead:
    diagnosis_id: UUID
    optimization_run_id: UUID
    workload_snapshot_id: UUID
    target_id: UUID
    ai_invocation_id: UUID
    schema_version: str
    source_snapshot_fingerprint: str
    deterministic_evidence_hash: str
    artifact_fingerprint: str
    findings: tuple[DiagnosisFinding, ...]


@dataclass(frozen=True)
class DiagnosisEvidenceView:
    """Literal-free, deterministic data exposed to the advisory provider."""

    snapshot_id: str
    snapshot_fingerprint: str
    target_id: str
    completeness: dict[str, Any]
    query_shapes: tuple[dict[str, Any], ...]
    metrics: tuple[dict[str, Any], ...]

    def canonical_json(self) -> str:
        return _canonical({
            "snapshot_id": self.snapshot_id,
            "snapshot_fingerprint": self.snapshot_fingerprint,
            "target_id": self.target_id,
            "completeness": self.completeness,
            "query_shapes": self.query_shapes,
            "metrics": self.metrics,
        })


class DiagnosisService:
    """Create/reuse one verified diagnosis artifact without holding a DB tx over AI."""

    def __init__(self, engine: AsyncEngine, provider: AIProvider, *, snapshots: WorkloadSnapshotService | None = None) -> None:
        self._engine = engine
        self._provider = provider
        self._snapshots = snapshots or WorkloadSnapshotService(engine)

    async def create_for_run(self, run_id: UUID) -> DiagnosisArtifactRead:
        existing = await self._artifact_for_run(run_id)
        if existing is not None:
            await self._validate_artifact(existing)
            return existing

        run, view = await self._load_valid_run_snapshot(run_id, require_diagnosing=True)
        evidence_json = view.canonical_json()
        input_hash = _sha256(evidence_json)
        reusable = await self._reusable_invocation(run_id, UUID(str(run["workload_snapshot_id"])), input_hash)
        if reusable is None:
            started = time.perf_counter()
            try:
                output = await self._provider.diagnose_artifact(
                    evidence_json,
                    allowed_query_shape_ids=tuple(row["query_shape_id"] for row in view.query_shapes),
                    allowed_evidence_refs=tuple(sorted(_allowed_evidence_refs(view))),
                )
                self._validate_output(output, view)
            except DiagnosisServiceError as error:
                await self._record_failed_invocation(run, input_hash, evidence_json, error.code)
                raise
            except ProviderError as error:
                code = DiagnosisFailureCode(error.code.value)
                await self._record_failed_invocation(run, input_hash, evidence_json, code)
                raise DiagnosisServiceError(code, retryable=error.retryable) from error
            except Exception as error:
                await self._record_failed_invocation(run, input_hash, evidence_json, DiagnosisFailureCode.AI_PROVIDER_UNAVAILABLE)
                raise DiagnosisServiceError(DiagnosisFailureCode.AI_PROVIDER_UNAVAILABLE, retryable=True) from error
            invocation_id = await self._record_successful_invocation(run, input_hash, evidence_json, output, (time.perf_counter() - started) * 1000)
        else:
            invocation_id, output = reusable

        return await self._persist_or_reuse(run, view, input_hash, invocation_id, output)

    async def verify_diagnosis_integrity(self, diagnosis_id: UUID) -> bool:
        artifact = await self._artifact_by_id(diagnosis_id)
        if artifact is None:
            raise DiagnosisServiceError(DiagnosisFailureCode.DIAGNOSIS_INTEGRITY_FAILURE)
        return await self._validate_artifact(artifact)

    async def _load_valid_run_snapshot(self, run_id: UUID, *, require_diagnosing: bool = False) -> tuple[RowMapping, DiagnosisEvidenceView]:
        async with self._engine.connect() as connection:
            run = (await connection.execute(select(models.OptimizationRun.__table__).where(models.OptimizationRun.__table__.c.id == run_id))).mappings().one_or_none()
        if run is None or run["workload_snapshot_id"] is None:
            raise DiagnosisServiceError(DiagnosisFailureCode.SNAPSHOT_MISSING)
        if require_diagnosing and _status(run["status"]) != models.RunStatus.DIAGNOSING.value:
            raise DiagnosisServiceError(DiagnosisFailureCode.SNAPSHOT_MISSING)
        snapshot = await self._snapshots.read(run["workload_snapshot_id"])
        if snapshot.metadata["source_run_id"] != run_id:
            raise DiagnosisServiceError(DiagnosisFailureCode.SNAPSHOT_RUN_MISMATCH)
        if snapshot.metadata["target_id"] != run["target_id"]:
            raise DiagnosisServiceError(DiagnosisFailureCode.SNAPSHOT_TARGET_MISMATCH)
        if not await self._snapshots.verify_snapshot_integrity(run["workload_snapshot_id"]):
            raise DiagnosisServiceError(DiagnosisFailureCode.SNAPSHOT_INTEGRITY_FAILURE)
        return run, _build_evidence_view(snapshot)

    async def _record_successful_invocation(self, run: RowMapping, input_hash: str, evidence_json: str, output: DiagnosisArtifactResult, latency_ms: float) -> UUID:
        now = datetime.now(timezone.utc)
        payload = output.model_dump(mode="json")
        async with self._engine.begin() as connection:
            attempt = int((await connection.execute(select(func.count()).select_from(models.AIInvocation.__table__).where(models.AIInvocation.__table__.c.optimization_run_id == run["id"], models.AIInvocation.__table__.c.stage == "DIAGNOSIS"))).scalar_one()) + 1
            invocation_id = uuid4()
            await connection.execute(insert(models.AIInvocation.__table__).values(
                id=invocation_id, created_at=now, updated_at=now, optimization_run_id=run["id"], stage="DIAGNOSIS",
                provider=self._provider.provider_name, model=self._provider.chat_model, prompt_version=PROMPT_VERSION,
                schema_version=SCHEMA_VERSION, workload_snapshot_id=run["workload_snapshot_id"], input_hash=input_hash,
                sanitized_input=json.loads(evidence_json), output_hash=_sha256(_canonical(payload)), validated_output=payload,
                latency_ms=latency_ms, status="SUCCEEDED", safe_error_code=None, completed_at=now, attempt_number=attempt,
            ))
        return invocation_id

    async def _record_failed_invocation(self, run: RowMapping, input_hash: str, evidence_json: str, code: DiagnosisFailureCode) -> None:
        now = datetime.now(timezone.utc)
        async with self._engine.begin() as connection:
            attempt = int((await connection.execute(select(func.count()).select_from(models.AIInvocation.__table__).where(models.AIInvocation.__table__.c.optimization_run_id == run["id"], models.AIInvocation.__table__.c.stage == "DIAGNOSIS"))).scalar_one()) + 1
            await connection.execute(insert(models.AIInvocation.__table__).values(
                id=uuid4(), created_at=now, updated_at=now, optimization_run_id=run["id"], stage="DIAGNOSIS",
                provider=self._provider.provider_name, model=self._provider.chat_model, prompt_version=PROMPT_VERSION,
                schema_version=SCHEMA_VERSION, workload_snapshot_id=run["workload_snapshot_id"], input_hash=input_hash,
                sanitized_input=json.loads(evidence_json), output_hash=None, validated_output=None, latency_ms=None,
                status="FAILED", safe_error_code=code.value, completed_at=now, attempt_number=attempt,
            ))

    async def _reusable_invocation(self, run_id: UUID, snapshot_id: UUID, input_hash: str) -> tuple[UUID, DiagnosisArtifactResult] | None:
        async with self._engine.connect() as connection:
            row = (await connection.execute(select(models.AIInvocation.__table__).where(
                models.AIInvocation.__table__.c.optimization_run_id == run_id,
                models.AIInvocation.__table__.c.stage == "DIAGNOSIS",
                models.AIInvocation.__table__.c.workload_snapshot_id == snapshot_id,
                models.AIInvocation.__table__.c.input_hash == input_hash,
                models.AIInvocation.__table__.c.prompt_version == PROMPT_VERSION,
                models.AIInvocation.__table__.c.schema_version == SCHEMA_VERSION,
                models.AIInvocation.__table__.c.status == "SUCCEEDED",
            ).order_by(models.AIInvocation.__table__.c.created_at, models.AIInvocation.__table__.c.id).limit(1))).mappings().one_or_none()
        if row is None or row["validated_output"] is None:
            return None
        try:
            return row["id"], DiagnosisArtifactResult.model_validate(row["validated_output"])
        except Exception as error:
            raise DiagnosisServiceError(DiagnosisFailureCode.DIAGNOSIS_SCHEMA_INVALID) from error

    async def _persist_or_reuse(self, run: RowMapping, view: DiagnosisEvidenceView, input_hash: str, invocation_id: UUID, output: DiagnosisArtifactResult) -> DiagnosisArtifactRead:
        async with self._engine.begin() as connection:
            locked = (await connection.execute(select(models.OptimizationRun.__table__).where(models.OptimizationRun.__table__.c.id == run["id"]).with_for_update())).mappings().one()
            existing = await self._artifact_for_run_in(connection, run["id"])
            if existing is not None:
                await self._validate_artifact(existing)
                return existing
            if _status(locked["status"]) != models.RunStatus.DIAGNOSING.value:
                raise DiagnosisServiceError(DiagnosisFailureCode.SNAPSHOT_MISSING)
            now = datetime.now(timezone.utc)
            diagnosis_id = uuid4()
            findings = tuple(sorted(output.findings, key=lambda item: item.finding_id))
            fingerprint = _artifact_fingerprint(run, view, input_hash, invocation_id, findings)
            try:
                await connection.execute(insert(models.DiagnosisArtifact.__table__).values(
                    id=diagnosis_id, created_at=now, updated_at=now, optimization_run_id=run["id"], workload_snapshot_id=run["workload_snapshot_id"],
                    target_id=run["target_id"], ai_invocation_id=invocation_id, schema_version=SCHEMA_VERSION,
                    source_snapshot_fingerprint=view.snapshot_fingerprint, deterministic_evidence_hash=input_hash, artifact_fingerprint=fingerprint,
                ))
                for finding in findings:
                    await connection.execute(insert(models.DiagnosisFinding.__table__).values(
                        id=uuid4(), created_at=now, updated_at=now, diagnosis_artifact_id=diagnosis_id, finding_id=finding.finding_id,
                        finding_type=finding.finding_type.value, summary=finding.summary, rationale=finding.rationale,
                        query_shape_ids=list(finding.query_shape_ids), evidence_refs=list(finding.evidence_refs),
                    ))
            except IntegrityError:
                # A competing caller may have committed the unique run artifact.
                existing = await self._artifact_for_run_in(connection, run["id"])
                if existing is None:
                    raise
                await self._validate_artifact(existing)
                return existing
        artifact = await self._artifact_by_id(diagnosis_id)
        assert artifact is not None
        await self._validate_artifact(artifact)
        return artifact

    async def _artifact_for_run(self, run_id: UUID) -> DiagnosisArtifactRead | None:
        async with self._engine.connect() as connection:
            return await self._artifact_for_run_in(connection, run_id)

    async def _artifact_by_id(self, diagnosis_id: UUID) -> DiagnosisArtifactRead | None:
        async with self._engine.connect() as connection:
            parent = (await connection.execute(select(models.DiagnosisArtifact.__table__).where(models.DiagnosisArtifact.__table__.c.id == diagnosis_id))).mappings().one_or_none()
            return await self._artifact_from_parent(connection, parent)

    async def _artifact_for_run_in(self, connection: AsyncConnection, run_id: UUID) -> DiagnosisArtifactRead | None:
        parent = (await connection.execute(select(models.DiagnosisArtifact.__table__).where(models.DiagnosisArtifact.__table__.c.optimization_run_id == run_id))).mappings().one_or_none()
        return await self._artifact_from_parent(connection, parent)

    async def _artifact_from_parent(self, connection: AsyncConnection, parent: RowMapping | None) -> DiagnosisArtifactRead | None:
        if parent is None:
            return None
        rows = tuple((await connection.execute(select(models.DiagnosisFinding.__table__).where(models.DiagnosisFinding.__table__.c.diagnosis_artifact_id == parent["id"]).order_by(models.DiagnosisFinding.__table__.c.finding_id))).mappings().all())
        findings = tuple(DiagnosisFinding(
            finding_id=row["finding_id"], finding_type=row["finding_type"], summary=row["summary"], rationale=row["rationale"],
            query_shape_ids=tuple(row["query_shape_ids"]), evidence_refs=tuple(row["evidence_refs"]),
        ) for row in rows)
        return DiagnosisArtifactRead(parent["id"], parent["optimization_run_id"], parent["workload_snapshot_id"], parent["target_id"], parent["ai_invocation_id"], parent["schema_version"], parent["source_snapshot_fingerprint"], parent["deterministic_evidence_hash"], parent["artifact_fingerprint"], findings)

    async def _validate_artifact(self, artifact: DiagnosisArtifactRead) -> bool:
        run, view = await self._load_valid_run_snapshot(artifact.optimization_run_id)
        if artifact.workload_snapshot_id != run["workload_snapshot_id"] or artifact.target_id != run["target_id"] or artifact.source_snapshot_fingerprint != view.snapshot_fingerprint:
            raise DiagnosisServiceError(DiagnosisFailureCode.DIAGNOSIS_INTEGRITY_FAILURE)
        self._validate_output(DiagnosisArtifactResult(findings=artifact.findings), view)
        actual = _artifact_fingerprint(run, view, artifact.deterministic_evidence_hash, artifact.ai_invocation_id, artifact.findings)
        if actual != artifact.artifact_fingerprint:
            raise DiagnosisServiceError(DiagnosisFailureCode.DIAGNOSIS_INTEGRITY_FAILURE)
        return True

    @staticmethod
    def _validate_output(output: DiagnosisArtifactResult, view: DiagnosisEvidenceView) -> None:
        query_shape_ids = {row["query_shape_id"] for row in view.query_shapes}
        evidence_refs = _allowed_evidence_refs(view)
        seen: set[str] = set()
        for finding in output.findings:
            if finding.finding_id in seen:
                raise DiagnosisServiceError(DiagnosisFailureCode.DIAGNOSIS_SCHEMA_INVALID)
            seen.add(finding.finding_id)
            if not set(finding.query_shape_ids).issubset(query_shape_ids):
                raise DiagnosisServiceError(DiagnosisFailureCode.UNKNOWN_QUERY_SHAPE_REFERENCE)
            if not set(finding.evidence_refs).issubset(evidence_refs):
                raise DiagnosisServiceError(DiagnosisFailureCode.UNKNOWN_EVIDENCE_REFERENCE)


def _build_evidence_view(snapshot: SnapshotRead) -> DiagnosisEvidenceView:
    metadata = snapshot.metadata
    completeness = dict(metadata["completeness"] or {})
    shapes = tuple({
        "query_shape_id": str(row["query_shape_id"]), "evidence_ref": "QS:" + str(row["id"]),
        "query_shape_hash": str(row["query_shape_hash"]), "operation": str(row["operation"]), "namespace": str(row["namespace"]),
        "workload_operation_share": float(row["workload_operation_share"]), "execution_time_share": _number(row["execution_time_share"]),
        "base_protected": bool(row["base_protected"]), "protection": {"manual": bool(row["protected_manual_critical"]), "operation_share": bool(row["protected_operation_share"]), "execution_share": bool(row["protected_execution_time_share"])},
        "provider": str(row["provider"]),
    } for row in snapshot.query_shapes)
    metrics = tuple({
        "evidence_ref": "METRIC:" + str(row["id"]), "scope": str(row["scope"]), "metric_name": str(row["metric_name"]), "metric_value": float(row["metric_value"]),
    } for row in snapshot.metrics)
    return DiagnosisEvidenceView(str(metadata["id"]), str(metadata["fingerprint"]), str(metadata["target_id"]), completeness, shapes, metrics)


def _artifact_fingerprint(run: RowMapping, view: DiagnosisEvidenceView, evidence_hash: str, invocation_id: UUID, findings: tuple[DiagnosisFinding, ...]) -> str:
    return _sha256(_canonical({"schema_version": SCHEMA_VERSION, "run_id": str(run["id"]), "snapshot_id": view.snapshot_id, "snapshot_fingerprint": view.snapshot_fingerprint, "target_id": str(run["target_id"]), "evidence_hash": evidence_hash, "ai_invocation_id": str(invocation_id), "findings": [item.model_dump(mode="json") for item in sorted(findings, key=lambda item: item.finding_id)]}))


def _allowed_evidence_refs(view: DiagnosisEvidenceView) -> set[str]:
    refs = {"SNAPSHOT:" + view.snapshot_id}
    refs.update(row["evidence_ref"] for row in view.query_shapes)
    refs.update(row["evidence_ref"] for row in view.metrics)
    return refs


def _status(value: object) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)


def _number(value: object) -> float | None:
    return float(cast(str, value)) if value is not None else None


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
