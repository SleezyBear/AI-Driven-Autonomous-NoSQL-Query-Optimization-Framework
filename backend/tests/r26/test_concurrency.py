from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.approvals.durable import DurableApprovalRequired, DurableApprovalService
from app.autonomy.policy import DeploymentMode
from app.runs.service import OptimizationRunCreationService


async def _principals_and_target(engine: AsyncEngine) -> tuple[UUID, UUID, UUID, UUID]:
    requester, approver_one, approver_two, target = uuid4(), uuid4(), uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    async with engine.begin() as connection:
        for identity, role in (
            (requester, "OPERATOR"),
            (approver_one, "APPROVER"),
            (approver_two, "APPROVER"),
        ):
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id,created_at,updated_at,email,password_hash,role,status,failed_login_count) "
                    "VALUES (:id,:now,:now,:email,'hash',:role,'ACTIVE',0)"
                ),
                {"id": identity, "now": now, "email": f"r26-{identity}@example.test", "role": role},
            )
        await connection.execute(
            text(
                "INSERT INTO targets "
                "(id,created_at,updated_at,owner_user_id,name,deployment_mode,state,connection_label,is_active) "
                "VALUES (:id,:now,:now,:owner,:name,'APPROVAL_CONTROLLED','ACTIVE','r26',true)"
            ),
            {"id": target, "now": now, "owner": requester, "name": f"r26-{target}"},
        )
    return requester, approver_one, approver_two, target


@pytest.mark.asyncio
async def test_concurrent_run_creation_is_atomic_and_never_orphans_jobs(
    disposable_r26_database: str,
) -> None:
    engine = create_async_engine(disposable_r26_database)
    requester, _one, _two, target = await _principals_and_target(engine)
    service = OptimizationRunCreationService(engine)
    try:
        results = await asyncio.gather(
            *(
                service.create_run_with_initial_job(
                    target_id=target,
                    requested_by_user_id=requester,
                    deployment_mode=DeploymentMode.APPROVAL_CONTROLLED,
                    primary_metric_key="p99_latency_ms",
                )
                for _ in range(40)
            )
        )
        run_ids = [row.run["id"] for row in results]
        assert len(run_ids) == len(set(run_ids)) == 40
        async with engine.connect() as connection:
            joined = await connection.scalar(
                text(
                    "SELECT count(*) FROM optimization_runs r JOIN jobs j "
                    "ON j.optimization_run_id=r.id WHERE r.id=ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": run_ids},
            )
            duplicates = await connection.scalar(
                text(
                    "SELECT count(*) FROM (SELECT optimization_run_id FROM jobs "
                    "WHERE optimization_run_id=ANY(CAST(:ids AS uuid[])) "
                    "GROUP BY optimization_run_id HAVING count(*)<>1) q"
                ),
                {"ids": run_ids},
            )
        assert joined == 40 and duplicates == 0
    finally:
        await engine.dispose()


async def _pending_approval(
    engine: AsyncEngine, requester: UUID, target: UUID
) -> tuple[UUID, UUID]:
    run_id, candidate_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO optimization_runs "
                "(id,created_at,updated_at,target_id,status,requested_by_user_id,deployment_mode) "
                "VALUES (:id,:now,:now,:target,'APPROVAL_PENDING',:requester,'APPROVAL_CONTROLLED')"
            ),
            {"id": run_id, "now": now, "target": target, "requester": requester},
        )
    request = await DurableApprovalService(engine).request(
        action_id=f"action-{run_id}",
        target_id=target,
        candidate_id=candidate_id,
        candidate_fingerprint=f"fingerprint-{candidate_id}",
        evidence_hash=f"evidence-{run_id}",
        requester_id=requester,
        optimization_run_id=run_id,
    )
    return run_id, request["id"]


@pytest.mark.asyncio
async def test_approval_races_have_one_decision_and_at_most_one_continuation(
    disposable_r26_database: str,
) -> None:
    engine = create_async_engine(disposable_r26_database)
    requester, approver_one, approver_two, target = await _principals_and_target(engine)
    service = DurableApprovalService(engine)
    try:
        for trial in range(12):
            run_id, approval_id = await _pending_approval(engine, requester, target)
            if trial % 2:
                operations = (
                    service.approve_and_enqueue_continuation(approval_id, approver_one),
                    service.approve_and_enqueue_continuation(approval_id, approver_two),
                )
            else:
                operations = (
                    service.approve_and_enqueue_continuation(approval_id, approver_one),
                    service.reject_and_complete_run(approval_id, approver_two, "race"),
                )
            outcomes = await asyncio.gather(*operations, return_exceptions=True)
            assert sum(not isinstance(outcome, Exception) for outcome in outcomes) == 1
            assert sum(isinstance(outcome, DurableApprovalRequired) for outcome in outcomes) == 1
            async with engine.connect() as connection:
                decision_count = await connection.scalar(
                    text("SELECT count(*) FROM approval_decisions WHERE approval_request_id=:id"),
                    {"id": approval_id},
                )
                continuation_count = await connection.scalar(
                    text(
                        "SELECT count(*) FROM jobs WHERE optimization_run_id=:run "
                        "AND payload->>'continuation'='true'"
                    ),
                    {"run": run_id},
                )
                status = await connection.scalar(
                    text("SELECT status::text FROM optimization_runs WHERE id=:id"),
                    {"id": run_id},
                )
            assert decision_count == 1
            assert continuation_count == (1 if status == "APPROVED" else 0)
            with pytest.raises(DurableApprovalRequired):
                await service.approve_and_enqueue_continuation(approval_id, approver_two)
    finally:
        await engine.dispose()
