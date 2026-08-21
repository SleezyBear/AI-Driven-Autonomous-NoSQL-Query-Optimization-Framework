"""Phase 33 acceptance tests for ownership-verified index rollback."""

import pytest

from app.actions.schemas import CreateIndexAction
from app.adapters.contracts import IndexSpec, Namespace
from app.adapters.fake import FakeDatabaseAdapter
from app.admission.models import AdmissionResult, AdmissionStatus, BenchmarkProfile
from app.approvals.flow import ApprovalFlow
from app.ledger.chain import AppendOnlyLedger
from app.production.executor import DeploymentRequest, ProductionExecutor
from app.rollback.owned_index import OwnedIndexRollbacker, RollbackRequest, RollbackStatus


def _action() -> CreateIndexAction:
    return CreateIndexAction(database="commerce", collection="orders", index_name="customer_created", fields=({"field": "customer_id", "direction": 1},))


def _admission() -> AdmissionResult:
    return AdmissionResult("candidate-1", "evaluation-1", BenchmarkProfile.AUTONOMOUS, "latency", 1, 1, AdmissionStatus.ADMITTED, (), production_eligible=True)


async def _deployed() -> tuple[FakeDatabaseAdapter, AppendOnlyLedger, str]:
    adapter = FakeDatabaseAdapter((Namespace(collection="orders"),))
    ledger = AppendOnlyLedger()
    approvals = ApprovalFlow()
    executor = ProductionExecutor(adapter, approvals, ledger)
    action = _action()
    approval = approvals.request("candidate-1", "evidence-a", "target-1")
    approvals.approve(approval.approval_id, "operator@example.test")
    result = await executor.deploy(DeploymentRequest("target-1", "candidate-1", action, _admission(), "evidence-a", await executor.current_state_hash(action), "production-executor"))
    return adapter, ledger, result.applied_entry.entry_id


@pytest.mark.asyncio
async def test_successfully_rolls_back_exactly_ledger_owned_index() -> None:
    adapter, ledger, entry_id = await _deployed()
    rollback = OwnedIndexRollbacker(adapter, ledger)

    result = await rollback.rollback(RollbackRequest("target-1", entry_id, "rollback-worker"))

    assert result.status is RollbackStatus.ROLLED_BACK
    assert await adapter.list_indexes(Namespace(collection="orders")) == ()
    assert result.ledger_entry is not None
    assert result.ledger_entry.forward_action["phase"] == "ROLLED_BACK"


@pytest.mark.asyncio
async def test_drift_rejection_returns_rollback_blocked_without_modification() -> None:
    adapter, ledger, entry_id = await _deployed()
    await adapter.create_index(Namespace(collection="orders"), IndexSpec("drift", (("status", 1),)))
    rollback = OwnedIndexRollbacker(adapter, ledger)

    result = await rollback.rollback(RollbackRequest("target-1", entry_id, "rollback-worker"))

    assert result.status is RollbackStatus.ROLLBACK_BLOCKED
    assert "RELEVANT_DRIFT_DETECTED" in result.reason_codes
    assert [index.name for index in await adapter.list_indexes(Namespace(collection="orders"))] == ["customer_created", "drift"]
