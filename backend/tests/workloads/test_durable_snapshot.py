"""R19E durable workload snapshot tests against real PostgreSQL."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from pymongo import AsyncMongoClient

from app.autonomy.policy import DeploymentMode
from app.runs.orchestrator import OptimizationRunOrchestrator, OrchestrationOutcome
from app.runs.service import OptimizationRunCreationService
from app.worker.durable import ExecutionContext
from app.workloads.durable import SnapshotFailureCode, WorkloadSnapshotError, WorkloadSnapshotService
from app.telemetry.persistence import TelemetryPersistenceService
from app.telemetry.providers import CurrentOpTelemetryProvider


async def _run(engine: object) -> tuple[UUID, UUID, UUID]:
    marker = uuid4().hex
    async with engine.begin() as connection:  # type: ignore[union-attr]
        user = UUID(str((await connection.execute(text("INSERT INTO users (id,created_at,updated_at,email,password_hash,role,status,failed_login_count) VALUES(gen_random_uuid(),now(),now(),:email,'hash','OPERATOR','ACTIVE',0) RETURNING id"), {"email": f"{marker}@example.test"})).scalar_one()))
        target = UUID(str((await connection.execute(text("INSERT INTO targets (id,created_at,updated_at,owner_user_id,name,deployment_mode,state,connection_label,is_active) VALUES(gen_random_uuid(),now(),now(),:owner,:name,'APPROVAL_CONTROLLED','ACTIVE','monitored',true) RETURNING id"), {"owner": user, "name": marker})).scalar_one()))
        evaluation = UUID(str((await connection.execute(text("INSERT INTO targets (id,created_at,updated_at,owner_user_id,name,deployment_mode,state,connection_label,is_active) VALUES(gen_random_uuid(),now(),now(),:owner,:name,'APPROVAL_CONTROLLED','ACTIVE','evaluation',true) RETURNING id"), {"owner": user, "name": marker + "e"})).scalar_one()))
        await connection.execute(text("INSERT INTO evaluation_mappings (id,created_at,updated_at,target_id,evaluation_target_id,mapping_status) VALUES(gen_random_uuid(),now(),now(),:target,:evaluation,'ACTIVE')"), {"target": target, "evaluation": evaluation})
    created = await OptimizationRunCreationService(engine).create_run_with_initial_job(target_id=target, requested_by_user_id=user, deployment_mode=DeploymentMode.APPROVAL_CONTROLLED, primary_metric_key=None)
    async with engine.begin() as connection:  # type: ignore[union-attr]
        await connection.execute(text("UPDATE optimization_runs SET status='SNAPSHOTTING' WHERE id=:id"), {"id": created.run["id"]})
    return user, target, UUID(str(created.run["id"]))


async def _telemetry(engine: object, target: UUID, *, stale: bool = False, secret: bool = False) -> None:
    now = datetime.now(timezone.utc) - (timedelta(seconds=400) if stale else timedelta(seconds=1))
    async with engine.begin() as connection:  # type: ignore[union-attr]
        namespace = UUID(str((await connection.execute(text("INSERT INTO namespaces (id,created_at,updated_at,target_id,name,allowlisted) VALUES(gen_random_uuid(),now(),now(),:target,:name,true) RETURNING id"), {"target": target, "name": "orders"})).scalar_one()))
        shape = UUID(str((await connection.execute(text("INSERT INTO query_shapes (id,created_at,updated_at,namespace_id,shape_hash,normalized_shape,operation) VALUES(gen_random_uuid(),now(),now(),:namespace,:hash,CAST(:shape AS json),'find') RETURNING id"), {"namespace": namespace, "hash": "shape-" + uuid4().hex, "shape": '{\"filter\":\"SNAPSHOT_SECRET_CANARY@example.test\"}' if secret else '{\"filter\":\"<string>\"}'})).scalar_one()))
        window = UUID(str((await connection.execute(text("INSERT INTO telemetry_windows (id,created_at,updated_at,target_id,started_at,ended_at,source,status) VALUES(gen_random_uuid(),now(),now(),:target,:start,:end,'QUERY_STATS','COMPLETED') RETURNING id"), {"target": target, "start": now - timedelta(seconds=5), "end": now})).scalar_one()))
        for name, value in (("operation_count", 100), ("aggregate_execution_time_ms", 1000), ("manually_critical", 0)):
            await connection.execute(text("INSERT INTO metric_observations (id,created_at,updated_at,telemetry_window_id,query_shape_id,metric_name,metric_value,observed_at) VALUES(gen_random_uuid(),now(),now(),:window,:shape,:name,:value,:at)"), {"window": window, "shape": shape, "name": name, "value": value, "at": now})


@pytest.mark.asyncio
async def test_snapshot_is_idempotent_immutable_and_restart_safe(disposable_workload_database: str) -> None:
    engine = create_async_engine(disposable_workload_database)
    user, target, run = await _run(engine)
    try:
        await _telemetry(engine, target)
        service = WorkloadSnapshotService(engine)
        first = await service.create_for_run(run)
        second = await service.create_for_run(run)
        assert first.snapshot_id == second.snapshot_id and second.reused
        assert await service.verify_snapshot_integrity(first.snapshot_id)
        await engine.dispose()
        engine = create_async_engine(disposable_workload_database)
        assert await WorkloadSnapshotService(engine).verify_snapshot_integrity(first.snapshot_id)
        async with engine.begin() as connection:
            with pytest.raises(Exception, match="immutable"):
                await connection.execute(text("UPDATE workload_snapshots SET fingerprint='bad' WHERE id=:id"), {"id": first.snapshot_id})
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_no_source_stale_and_transactional_failure(disposable_workload_database: str) -> None:
    engine = create_async_engine(disposable_workload_database)
    user, target, run = await _run(engine)
    try:
        with pytest.raises(WorkloadSnapshotError) as no_source:
            await WorkloadSnapshotService(engine).create_for_run(run)
        assert no_source.value.code is SnapshotFailureCode.NO_COMPLETED_TELEMETRY
        await _telemetry(engine, target, stale=True)
        with pytest.raises(WorkloadSnapshotError) as stale:
            await WorkloadSnapshotService(engine).create_for_run(run)
        assert stale.value.code is SnapshotFailureCode.STALE_TELEMETRY
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_snapshot_and_orchestrator_resume(disposable_workload_database: str) -> None:
    engine = create_async_engine(disposable_workload_database)
    user, target, run = await _run(engine)
    try:
        await _telemetry(engine, target)
        one, two = await asyncio.gather(WorkloadSnapshotService(engine).create_for_run(run), WorkloadSnapshotService(engine).create_for_run(run))
        assert one.snapshot_id == two.snapshot_id
        result = await OptimizationRunOrchestrator(engine).run(run, ExecutionContext(asyncio.Event()))
        assert result.outcome is OrchestrationOutcome.PROGRESSED and result.status.value == "DIAGNOSING"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_monitored_mongo_currentop_to_postgres_to_snapshot(disposable_workload_database: str) -> None:
    """The real path is currentOp-only, therefore not autonomy-qualified."""
    engine = create_async_engine(disposable_workload_database)
    user, target, run = await _run(engine)
    uri = "mongodb://control_plane_root:control_plane_root_dev_only@127.0.0.1:27017/admin?authSource=admin&directConnection=true"
    client: AsyncMongoClient[object] = AsyncMongoClient(uri)
    try:
        collection = client.get_database(f"r19e_snapshot_acceptance_{uuid4().hex}").get_collection("orders")
        inserted = await collection.insert_one({"customer_email": "SNAPSHOT_SECRET_CANARY@example.test", "order_token": "SNAPSHOT_PRIVATE_123"})

        async def slow_query() -> None:
            await collection.find_one({"$where": "sleep(2500) || true"})

        pending = asyncio.create_task(slow_query())
        await asyncio.sleep(0.25)
        provider = CurrentOpTelemetryProvider(client.get_database("admin"))
        assert await provider.available()
        window_id = await TelemetryPersistenceService(engine).collect_and_persist(target, provider)
        await pending
        result = await WorkloadSnapshotService(engine).create_for_run(run)
        snapshot = await WorkloadSnapshotService(engine).read(result.snapshot_id)
        assert {row["telemetry_window_id"] for row in snapshot.source_windows} == {window_id}
        assert snapshot.metadata["target_id"] == target
        assert snapshot.metadata["completeness"]["providers"] == ["CURRENT_OP"]
        assert snapshot.metadata["completeness"]["production_autonomy_eligible"] is False
        assert snapshot.query_shapes and sum(float(row["workload_operation_share"]) for row in snapshot.query_shapes) == pytest.approx(1.0)
        assert await WorkloadSnapshotService(engine).verify_snapshot_integrity(result.snapshot_id)
        async with engine.connect() as connection:
            stored = (await connection.execute(text("SELECT coalesce(snapshot::text,'') || coalesce(completeness::text,'') FROM workload_snapshots WHERE id=:id"), {"id": result.snapshot_id})).scalar_one()
            assert "SNAPSHOT_SECRET_CANARY" not in stored and "SNAPSHOT_PRIVATE_123" not in stored
            assert (await connection.execute(text("SELECT workload_snapshot_id FROM optimization_runs WHERE id=:id"), {"id": run})).scalar_one() == result.snapshot_id
    finally:
        if "inserted" in locals():
            await collection.delete_one({"_id": inserted.inserted_id})
        await client.close()
        await engine.dispose()
