"""R19F real-PostgreSQL durable diagnosis contract tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.ai.provider import DiagnosisArtifactResult, DiagnosisFinding, DiagnosisFindingType, FakeAIProvider
from app.autonomy.policy import DeploymentMode
from app.diagnosis.durable import DiagnosisFailureCode, DiagnosisService, DiagnosisServiceError
from app.runs.orchestrator import OptimizationRunOrchestrator, OrchestrationOutcome
from app.runs.service import OptimizationRunCreationService
from app.worker.durable import ExecutionContext
from app.workloads.durable import WorkloadSnapshotService


class ControlledProvider(FakeAIProvider):
    def __init__(self, output: DiagnosisArtifactResult) -> None:
        self.output = output
        self.calls = 0

    async def diagnose_artifact(self, evidence: str, **_: object) -> DiagnosisArtifactResult:
        self.calls += 1
        return self.output


async def _run_with_snapshot(engine: AsyncEngine) -> tuple[UUID, UUID, UUID]:
    marker = uuid4().hex
    async with engine.begin() as connection:
        user = UUID(str((await connection.execute(text("INSERT INTO users (id,created_at,updated_at,email,password_hash,role,status,failed_login_count) VALUES(gen_random_uuid(),now(),now(),:email,'hash','OPERATOR','ACTIVE',0) RETURNING id"), {"email": f"{marker}@example.test"})).scalar_one()))
        target = UUID(str((await connection.execute(text("INSERT INTO targets (id,created_at,updated_at,owner_user_id,name,deployment_mode,state,connection_label,is_active) VALUES(gen_random_uuid(),now(),now(),:owner,:name,'APPROVAL_CONTROLLED','ACTIVE','monitored',true) RETURNING id"), {"owner": user, "name": marker})).scalar_one()))
        evaluation = UUID(str((await connection.execute(text("INSERT INTO targets (id,created_at,updated_at,owner_user_id,name,deployment_mode,state,connection_label,is_active) VALUES(gen_random_uuid(),now(),now(),:owner,:name,'APPROVAL_CONTROLLED','ACTIVE','evaluation',true) RETURNING id"), {"owner": user, "name": marker + "e"})).scalar_one()))
        await connection.execute(text("INSERT INTO evaluation_mappings (id,created_at,updated_at,target_id,evaluation_target_id,mapping_status) VALUES(gen_random_uuid(),now(),now(),:target,:evaluation,'ACTIVE')"), {"target": target, "evaluation": evaluation})
    created = await OptimizationRunCreationService(engine).create_run_with_initial_job(target_id=target, requested_by_user_id=user, deployment_mode=DeploymentMode.APPROVAL_CONTROLLED, primary_metric_key=None)
    run = UUID(str(created.run["id"]))
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    async with engine.begin() as connection:
        namespace = UUID(str((await connection.execute(text("INSERT INTO namespaces (id,created_at,updated_at,target_id,name,allowlisted) VALUES(gen_random_uuid(),now(),now(),:target,'orders',true) RETURNING id"), {"target": target})).scalar_one()))
        shape = UUID(str((await connection.execute(text("INSERT INTO query_shapes (id,created_at,updated_at,namespace_id,shape_hash,normalized_shape,operation) VALUES(gen_random_uuid(),now(),now(),:namespace,:hash,CAST(:shape AS json),'find') RETURNING id"), {"namespace": namespace, "hash": "shape-" + marker, "shape": '{"filter":"DIAGNOSIS_SECRET_CANARY@example.test"}'})).scalar_one()))
        window = UUID(str((await connection.execute(text("INSERT INTO telemetry_windows (id,created_at,updated_at,target_id,started_at,ended_at,source,status) VALUES(gen_random_uuid(),now(),now(),:target,:start,:end,'QUERY_STATS','COMPLETED') RETURNING id"), {"target": target, "start": now - timedelta(seconds=5), "end": now})).scalar_one()))
        for name, value in (("operation_count", 100), ("aggregate_execution_time_ms", 1000), ("manually_critical", 0)):
            await connection.execute(text("INSERT INTO metric_observations (id,created_at,updated_at,telemetry_window_id,query_shape_id,metric_name,metric_value,observed_at) VALUES(gen_random_uuid(),now(),now(),:window,:shape,:name,:value,:at)"), {"window": window, "shape": shape, "name": name, "value": value, "at": now})
        await connection.execute(text("UPDATE optimization_runs SET status='SNAPSHOTTING' WHERE id=:id"), {"id": run})
    snapshot = await WorkloadSnapshotService(engine).create_for_run(run)
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE optimization_runs SET status='DIAGNOSING' WHERE id=:id"), {"id": run})
    return target, run, snapshot.snapshot_id


async def _provider(engine: AsyncEngine, snapshot_id: UUID, *, unknown: bool = False, empty: bool = False) -> ControlledProvider:
    snapshot = await WorkloadSnapshotService(engine).read(snapshot_id)
    if empty:
        return ControlledProvider(DiagnosisArtifactResult())
    shape = snapshot.query_shapes[0]
    finding = DiagnosisFinding(
        finding_id="finding-1", finding_type=DiagnosisFindingType.QUERY_LATENCY_HOTSPOT,
        summary="Latency evidence is concentrated in an observed shape.", rationale="The supplied snapshot records concentrated execution time.",
        query_shape_ids=("unknown" if unknown else str(shape["query_shape_id"]),), evidence_refs=("QS:unknown" if unknown else "QS:" + str(shape["id"]),),
    )
    return ControlledProvider(DiagnosisArtifactResult(findings=(finding,)))


@pytest.mark.asyncio
async def test_diagnosis_is_durable_reusable_and_literal_free(disposable_diagnosis_database: str) -> None:
    engine = create_async_engine(disposable_diagnosis_database)
    try:
        _, run, snapshot_id = await _run_with_snapshot(engine)
        provider = await _provider(engine, snapshot_id)
        service = DiagnosisService(engine, provider)
        first = await service.create_for_run(run)
        second = await service.create_for_run(run)
        assert first.diagnosis_id == second.diagnosis_id
        assert provider.calls == 1 and await service.verify_diagnosis_integrity(first.diagnosis_id)
        async with engine.connect() as connection:
            stored = str((await connection.execute(text("SELECT sanitized_input::text || validated_output::text FROM ai_invocations WHERE id=:id"), {"id": first.ai_invocation_id})).scalar_one())
        assert "DIAGNOSIS_SECRET_CANARY" not in stored
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_invalid_reference_rejects_without_artifact(disposable_diagnosis_database: str) -> None:
    engine = create_async_engine(disposable_diagnosis_database)
    try:
        _, run, snapshot_id = await _run_with_snapshot(engine)
        service = DiagnosisService(engine, await _provider(engine, snapshot_id, unknown=True))
        with pytest.raises(DiagnosisServiceError) as error:
            await service.create_for_run(run)
        assert error.value.code in {DiagnosisFailureCode.UNKNOWN_QUERY_SHAPE_REFERENCE, DiagnosisFailureCode.UNKNOWN_EVIDENCE_REFERENCE}
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT count(*) FROM diagnosis_artifacts WHERE optimization_run_id=:run"), {"run": run})).scalar_one() == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_empty_concurrent_and_restart_safe(disposable_diagnosis_database: str) -> None:
    engine = create_async_engine(disposable_diagnosis_database)
    try:
        _, run, snapshot_id = await _run_with_snapshot(engine)
        provider = await _provider(engine, snapshot_id, empty=True)
        one, two = await asyncio.gather(DiagnosisService(engine, provider).create_for_run(run), DiagnosisService(engine, provider).create_for_run(run))
        assert one.diagnosis_id == two.diagnosis_id and not one.findings
        await engine.dispose()
        engine = create_async_engine(disposable_diagnosis_database)
        result = await DiagnosisService(engine, provider).create_for_run(run)
        assert result.diagnosis_id == one.diagnosis_id and await DiagnosisService(engine, provider).verify_diagnosis_integrity(result.diagnosis_id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_immutable_tamper_detected_and_orchestrator_transitions(disposable_diagnosis_database: str) -> None:
    engine = create_async_engine(disposable_diagnosis_database)
    try:
        _, run, snapshot_id = await _run_with_snapshot(engine)
        provider = await _provider(engine, snapshot_id)
        service = DiagnosisService(engine, provider)
        diagnosis = await service.create_for_run(run)
        with pytest.raises(Exception, match="immutable"):
            async with engine.begin() as connection:
                await connection.execute(text("UPDATE diagnosis_findings SET summary='tamper' WHERE diagnosis_artifact_id=:id"), {"id": diagnosis.diagnosis_id})
        async with engine.begin() as connection:
            await connection.execute(text("ALTER TABLE diagnosis_findings DISABLE TRIGGER diagnosis_findings_immutable"))
            await connection.execute(text("UPDATE diagnosis_findings SET summary='tamper' WHERE diagnosis_artifact_id=:id"), {"id": diagnosis.diagnosis_id})
            await connection.execute(text("ALTER TABLE diagnosis_findings ENABLE TRIGGER diagnosis_findings_immutable"))
        with pytest.raises(DiagnosisServiceError) as error:
            await service.verify_diagnosis_integrity(diagnosis.diagnosis_id)
        assert error.value.code is DiagnosisFailureCode.DIAGNOSIS_INTEGRITY_FAILURE
        # A fresh valid run demonstrates that the partial orchestrator stops at the next stage.
        _, next_run, next_snapshot = await _run_with_snapshot(engine)
        next_service = DiagnosisService(engine, await _provider(engine, next_snapshot, empty=True))
        result = await OptimizationRunOrchestrator(engine, diagnosis_service=next_service).run(next_run, ExecutionContext(asyncio.Event()))
        assert result.outcome is OrchestrationOutcome.PROGRESSED and result.status.value == "GENERATING_CANDIDATES"
    finally:
        await engine.dispose()
