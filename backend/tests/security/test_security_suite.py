"""Phase 48 zero-failure suite for the required security invariants."""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

os.environ.setdefault("JWT_SIGNING_KEY", "r48-test-signing-key-that-is-long-enough")

from app.actions.schemas import CreateIndexAction
from app.adapters.contracts import Namespace
from app.adapters.fake import FakeDatabaseAdapter
from app.admission.models import AdmissionResult, AdmissionStatus, BenchmarkProfile
from app.ai.provider import AIProvider, OllamaAIProvider
from app.approvals.flow import ApprovalFlow, ApprovalRequired, ApprovalStatus
from app.auth.routes import jwt_service
from app.auth.security import Principal, Role
from app.db import models
from app.db.runtime import create_control_plane_engine
from app.ledger.chain import AppendOnlyLedger
from app.main import app
from app.production.executor import DeploymentRequest, ProductionExecutor
from app.security.privacy import PrivacyBoundary, PrivacyMode
from app.security.redaction import redact_value


ROOT = Path(__file__).resolve().parents[3]
client = TestClient(app)


def _action() -> CreateIndexAction:
    return CreateIndexAction(database="commerce", collection="orders", index_name="customer_created", fields=({"field": "customer_id", "direction": 1},))


def _admission() -> AdmissionResult:
    return AdmissionResult("candidate-1", "evaluation-1", BenchmarkProfile.AUTONOMOUS, "latency", 1, 1, AdmissionStatus.ADMITTED, (), production_eligible=True)


def test_api_lacks_executor_secret_and_ai_lacks_database_credentials_or_tools() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()
    api_block = compose.split("\n  api:\n", 1)[1].split("\n  worker:\n", 1)[0]
    provider_source = inspect.getsource(AIProvider) + inspect.getsource(OllamaAIProvider)

    assert "executor" not in api_block.lower()
    assert "pymongo" not in provider_source.lower()
    assert not any("credential" in name.lower() or "database" in name.lower() for name in AIProvider.__dict__)
    assert not any(hasattr(AIProvider, name) for name in ("execute", "execute_tool", "tools", "database"))


def test_document_writes_fail_for_the_executor_credential() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/verify_mongodb_permissions.py"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_forbidden_actions_fail_validation() -> None:
    with pytest.raises(ValidationError):
        CreateIndexAction(database="commerce", collection="orders", index_name="unsafe", fields=({"field": "status", "direction": 1},), unique=True)


@pytest.mark.asyncio
async def test_cross_target_approval_reuse_and_stale_evidence_fail_before_mutation() -> None:
    adapter = FakeDatabaseAdapter((Namespace("orders"),))
    approvals = ApprovalFlow()
    executor = ProductionExecutor(adapter, approvals, AppendOnlyLedger())
    action = _action()
    approval = approvals.request("candidate-1", "evidence-a", "target-a")
    approvals.approve(approval.approval_id, "approver@example.test")

    cross_target = DeploymentRequest("target-b", "candidate-1", action, _admission(), "evidence-a", await executor.current_state_hash(action), "executor")
    with pytest.raises(ApprovalRequired, match="current approval required"):
        await executor.deploy(cross_target)
    stale = DeploymentRequest("target-a", "candidate-1", action, _admission(), "evidence-b", await executor.current_state_hash(action), "executor")
    with pytest.raises(ApprovalRequired, match="current approval required"):
        await executor.deploy(stale)

    assert flow_status(approvals, approval.approval_id) is ApprovalStatus.STALE
    assert await adapter.list_indexes(Namespace("orders")) == ()


@pytest.mark.asyncio
async def test_expired_approval_and_self_approval_fail() -> None:
    current = datetime(2026, 8, 21, tzinfo=timezone.utc)
    flow = ApprovalFlow(approval_ttl=timedelta(seconds=1), now=lambda: current)
    approval = flow.request("candidate-1", "evidence-a", "target-1")
    flow.approve(approval.approval_id, "approver@example.test")
    current += timedelta(seconds=2)

    with pytest.raises(ApprovalRequired, match="current approval required"):
        flow.require_current_approval("candidate-1", "evidence-a", "target-1")
    assert flow.get(approval.approval_id).status is ApprovalStatus.EXPIRED

    user_id = uuid4()
    engine = create_control_plane_engine()
    try:
        now = datetime.now(timezone.utc)
        async with engine.begin() as connection:
            await connection.execute(
                models.User.__table__.insert().values(
                    id=user_id,
                    created_at=now,
                    updated_at=now,
                    email=f"r48-{user_id.hex}@example.test",
                    password_hash="hash",
                    role=Role.APPROVER.value,
                    status="ACTIVE",
                    failed_login_count=0,
                )
            )
        with TestClient(app) as authenticated_client:
            response = authenticated_client.post(
                "/approvals/request-1",
                json={"requested_by_user_id": str(user_id)},
                headers={"Authorization": f"Bearer {jwt_service().issue(Principal(str(user_id), Role.APPROVER))}"},
            )
        assert response.status_code == 403
    finally:
        async with engine.begin() as connection:
            await connection.execute(models.User.__table__.delete().where(models.User.id == user_id))
        await engine.dispose()


def test_ledger_tampering_and_credential_logging_are_detected_or_redacted() -> None:
    ledger = AppendOnlyLedger()
    entry = ledger.append({"index": "before"}, {"index": "intended"}, {"index": "after"}, {"type": "CREATE_INDEX"}, {"type": "DROP_INDEX"}, "evidence", "actor")
    assert not AppendOnlyLedger.verify((replace(entry, after_state={"index": "tampered"}),))

    value = "mongodb://executor:unsafe-password@example.test/commerce"
    logged = str(redact_value({"authorization": "Bearer token", "uri": value}))
    evidence = PrivacyBoundary(PrivacyMode.LOCAL_NORMALIZED).serialize_for_postgres({"uri": value})
    assert "unsafe-password" not in logged
    assert "Bearer token" not in logged
    assert "unsafe-password" not in evidence


def flow_status(flow: ApprovalFlow, approval_id: str) -> ApprovalStatus:
    """Keep the security test's state assertion explicit and readable."""
    return flow.get(approval_id).status
