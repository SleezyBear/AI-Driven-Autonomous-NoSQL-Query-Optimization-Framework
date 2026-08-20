"""Phase 32 acceptance tests for the restricted production executor."""

import pytest

from app.actions.schemas import CreateIndexAction
from app.adapters.contracts import IndexSpec, Namespace
from app.adapters.fake import FakeDatabaseAdapter
from app.admission.models import AdmissionResult, AdmissionStatus, BenchmarkProfile
from app.approvals.flow import ApprovalFlow
from app.ledger.chain import AppendOnlyLedger
from app.production.executor import DeploymentRequest, ProductionExecutionError, ProductionExecutor


def _action() -> CreateIndexAction:
    return CreateIndexAction(
        database="commerce",
        collection="orders",
        index_name="customer_created",
        fields=({"field": "customer_id", "direction": 1},),
    )


def _admission(status: AdmissionStatus = AdmissionStatus.ADMITTED, production_eligible: bool = True) -> AdmissionResult:
    return AdmissionResult("candidate-1", "evaluation-1", BenchmarkProfile.AUTONOMOUS, "latency", 1, 1, status, (), production_eligible=production_eligible)


@pytest.mark.asyncio
async def test_deploys_only_after_the_full_typed_admitted_sequence() -> None:
    adapter = FakeDatabaseAdapter((Namespace(collection="orders"),))
    approvals = ApprovalFlow()
    ledger = AppendOnlyLedger()
    executor = ProductionExecutor(adapter, approvals, ledger)
    action = _action()
    evidence_hash = "evidence-a"
    approval = approvals.request("candidate-1", evidence_hash)
    approvals.approve(approval.approval_id, "operator@example.test")
    request = DeploymentRequest("target-1", "candidate-1", action, _admission(), evidence_hash, await executor.current_state_hash(action), "production-executor")

    result = await executor.deploy(request)

    indexes = await adapter.list_indexes(Namespace(collection="orders"))
    assert [index.name for index in indexes] == ["customer_created"]
    assert result.prepared_entry.forward_action["phase"] == "PREPARED"
    assert result.applied_entry.forward_action["phase"] == "APPLIED"
    assert AppendOnlyLedger.verify(ledger.entries)


@pytest.mark.asyncio
async def test_stale_approval_cannot_deploy_or_change_target() -> None:
    adapter = FakeDatabaseAdapter((Namespace(collection="orders"),))
    approvals = ApprovalFlow()
    executor = ProductionExecutor(adapter, approvals, AppendOnlyLedger())
    action = _action()
    approval = approvals.request("candidate-1", "evidence-a")
    approvals.approve(approval.approval_id, "operator@example.test")
    request = DeploymentRequest("target-1", "candidate-1", action, _admission(), "evidence-b", await executor.current_state_hash(action), "production-executor")

    with pytest.raises(PermissionError, match="current approval required"):
        await executor.deploy(request)

    assert await adapter.list_indexes(Namespace(collection="orders")) == ()


@pytest.mark.asyncio
async def test_unadmitted_action_is_rejected_without_execution() -> None:
    adapter = FakeDatabaseAdapter((Namespace(collection="orders"),))
    approvals = ApprovalFlow()
    executor = ProductionExecutor(adapter, approvals, AppendOnlyLedger())
    action = _action()
    approval = approvals.request("candidate-1", "evidence-a")
    approvals.approve(approval.approval_id, "operator@example.test")
    request = DeploymentRequest("target-1", "candidate-1", action, _admission(AdmissionStatus.REJECTED_REGRESSION), "evidence-a", await executor.current_state_hash(action), "production-executor")

    with pytest.raises(ProductionExecutionError, match="production-eligible admitted"):
        await executor.deploy(request)

    assert await adapter.list_indexes(Namespace(collection="orders")) == ()


@pytest.mark.asyncio
async def test_raw_action_is_rejected_before_any_adapter_operation() -> None:
    adapter = FakeDatabaseAdapter((Namespace(collection="orders"),))
    executor = ProductionExecutor(adapter, ApprovalFlow(), AppendOnlyLedger())
    request = DeploymentRequest("target-1", "candidate-1", object(), _admission(), "evidence-a", "state-a", "production-executor")  # type: ignore[arg-type]

    with pytest.raises(ProductionExecutionError, match="raw or unsupported"):
        await executor.deploy(request)

    assert await adapter.list_indexes(Namespace(collection="orders")) == ()


@pytest.mark.asyncio
async def test_target_state_drift_is_rejected_before_execution() -> None:
    adapter = FakeDatabaseAdapter((Namespace(collection="orders"),))
    approvals = ApprovalFlow()
    executor = ProductionExecutor(adapter, approvals, AppendOnlyLedger())
    action = _action()
    approval = approvals.request("candidate-1", "evidence-a")
    approvals.approve(approval.approval_id, "operator@example.test")
    expected_state_hash = await executor.current_state_hash(action)
    await adapter.create_index(Namespace(collection="orders"), IndexSpec("drift", (("status", 1),)))
    request = DeploymentRequest("target-1", "candidate-1", action, _admission(), "evidence-a", expected_state_hash, "production-executor")

    with pytest.raises(ProductionExecutionError, match="differs from verified evidence"):
        await executor.deploy(request)

    assert [index.name for index in await adapter.list_indexes(Namespace(collection="orders"))] == ["drift"]
