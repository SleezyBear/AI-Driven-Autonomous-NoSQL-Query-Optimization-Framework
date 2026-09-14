"""Black-box authenticated run and approval API contracts on isolated PostgreSQL."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.approvals.durable import DurableApprovalService
from app.auth.security import JwtService, Principal, Role
from app.db import models
from app.main import app


_KEY = "r19q-test-signing-key-that-is-long-enough"


async def _seed(database_url: str) -> tuple[UUID, UUID, UUID, UUID]:
    """Create operator/approver identities and a valid monitored/evaluation pair."""
    engine = create_async_engine(database_url)
    operator, approver, target, evaluation_target = uuid4(), uuid4(), uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    async with engine.begin() as connection:
        await connection.execute(
            models.User.__table__.insert(),
            [
                {"id": operator, "created_at": now, "updated_at": now, "email": "operator-r19q@example.test", "password_hash": "not-used", "role": Role.OPERATOR.value, "status": "ACTIVE", "failed_login_count": 0},
                {"id": approver, "created_at": now, "updated_at": now, "email": "approver-r19q@example.test", "password_hash": "not-used", "role": Role.APPROVER.value, "status": "ACTIVE", "failed_login_count": 0},
            ],
        )
        await connection.execute(
            models.Target.__table__.insert(),
            [
                {"id": target, "created_at": now, "updated_at": now, "owner_user_id": operator, "name": "monitored-r19q", "deployment_mode": "APPROVAL_CONTROLLED", "state": "ACTIVE", "connection_label": "monitored", "is_active": True},
                {"id": evaluation_target, "created_at": now, "updated_at": now, "owner_user_id": operator, "name": "evaluation-r19q", "deployment_mode": "APPROVAL_CONTROLLED", "state": "ACTIVE", "connection_label": "evaluation", "is_active": True},
            ],
        )
        await connection.execute(models.EvaluationMapping.__table__.insert().values(id=uuid4(), created_at=now, updated_at=now, target_id=target, evaluation_target_id=evaluation_target, mapping_status="ACTIVE"))
    await engine.dispose()
    return operator, approver, target, evaluation_target


def _headers(user_id: UUID, role: Role) -> dict[str, str]:
    token = JwtService(_KEY).issue(Principal(user_id=str(user_id), role=role))
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_authenticated_operator_creates_one_durable_run_and_job(
    disposable_api_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", disposable_api_database)
    monkeypatch.setenv("JWT_SIGNING_KEY", _KEY)
    operator, _, target, _ = await _seed(disposable_api_database)

    with TestClient(app) as client:
        response = client.post("/api/v1/runs", headers=_headers(operator, Role.OPERATOR), json={"target_id": str(target), "deployment_mode": "APPROVAL_CONTROLLED", "primary_metric_key": "p99_latency_ms"})
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["target_id"] == str(target)
        assert body["status"] == "CREATED"
        listed = client.get("/api/v1/runs?status=CREATED", headers=_headers(operator, Role.OPERATOR))
        assert listed.status_code == 200
        assert [item["run_id"] for item in listed.json()["records"]] == [body["run_id"]]
        detail = client.get(f"/api/v1/runs/{body['run_id']}", headers=_headers(operator, Role.OPERATOR))
        assert detail.status_code == 200
        assert detail.json()["run"]["run_id"] == body["run_id"]

    engine = create_async_engine(disposable_api_database)
    async with engine.connect() as connection:
        jobs = (await connection.execute(select(models.Job.__table__).where(models.Job.__table__.c.optimization_run_id == UUID(body["run_id"])))).mappings().all()
    await engine.dispose()
    assert len(jobs) == 1
    assert jobs[0]["kind"] == "OPTIMIZATION"


@pytest.mark.asyncio
async def test_approval_endpoint_enforces_four_eyes_and_enqueues_once(
    disposable_api_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", disposable_api_database)
    monkeypatch.setenv("JWT_SIGNING_KEY", _KEY)
    operator, approver, target, _ = await _seed(disposable_api_database)
    engine = create_async_engine(disposable_api_database)
    async with engine.begin() as connection:
        run = (await connection.execute(models.OptimizationRun.__table__.insert().values(id=uuid4(), created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc), target_id=target, workload_snapshot_id=None, status=models.RunStatus.APPROVAL_PENDING, requested_by_user_id=operator, deployment_mode="APPROVAL_CONTROLLED", primary_metric_key="p99_latency_ms").returning(models.OptimizationRun.__table__.c.id))).scalar_one()
    approval = await DurableApprovalService(engine).request(action_id="r19q-approval", target_id=target, candidate_id=uuid4(), evidence_hash="r19q-safe-evidence", requester_id=operator, optimization_run_id=run, candidate_fingerprint="r19q-fingerprint")
    await engine.dispose()

    with TestClient(app) as client:
        self_approval = client.post(f"/api/v1/approvals/{approval['id']}/approve", headers=_headers(operator, Role.OPERATOR), json={})
        assert self_approval.status_code == 403
        approved = client.post(f"/api/v1/approvals/{approval['id']}/approve", headers=_headers(approver, Role.APPROVER), json={})
        assert approved.status_code == 200, approved.text
        duplicate = client.post(f"/api/v1/approvals/{approval['id']}/approve", headers=_headers(approver, Role.APPROVER), json={})
        assert duplicate.status_code == 409

    engine = create_async_engine(disposable_api_database)
    async with engine.connect() as connection:
        jobs = (await connection.execute(select(models.Job.__table__).where(models.Job.__table__.c.optimization_run_id == run))).mappings().all()
        persisted_run = (await connection.execute(select(models.OptimizationRun.__table__.c.status).where(models.OptimizationRun.__table__.c.id == run))).scalar_one()
    await engine.dispose()
    assert persisted_run is models.RunStatus.APPROVED
    assert len(jobs) == 1
