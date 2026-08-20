"""Phase 35 acceptance tests for human-gated allowedIndexes query settings."""

import pytest

from app.actions.schemas import SetQuerySettingsIndexHintAction
from app.adapters.contracts import IndexSpec, Namespace, QuerySettingsIndexHint
from app.adapters.fake import FakeDatabaseAdapter
from app.approvals.flow import ApprovalFlow
from app.ledger.chain import AppendOnlyLedger
from app.production.executor import ProductionExecutionError
from app.production.query_settings import (
    QuerySettingsDeploymentRequest,
    QuerySettingsExecutor,
    QuerySettingsRollbackRequest,
)


async def _executor() -> tuple[FakeDatabaseAdapter, ApprovalFlow, AppendOnlyLedger, QuerySettingsExecutor]:
    adapter = FakeDatabaseAdapter((Namespace("orders"),))
    await adapter.create_index(Namespace("orders"), IndexSpec("customer_created", (("customer_id", 1),)))
    approvals = ApprovalFlow()
    ledger = AppendOnlyLedger()
    return adapter, approvals, ledger, QuerySettingsExecutor(adapter, approvals, ledger)


def _action(previous: tuple[str, ...] | None = None) -> SetQuerySettingsIndexHintAction:
    return SetQuerySettingsIndexHintAction(
        database="commerce",
        collection="orders",
        query_shape_hash="shape-a",
        allowed_indexes=("customer_created",),
        previous_allowed_indexes=previous,
    )


@pytest.mark.asyncio
async def test_deploys_allowed_indexes_only_and_rolls_back_to_absent_prior_state() -> None:
    adapter, approvals, ledger, executor = await _executor()
    action = _action()
    approval = approvals.request("action-a", "evidence-a")
    approvals.approve(approval.approval_id, "approver@example.test")
    result = await executor.deploy(
        QuerySettingsDeploymentRequest("target-a", "action-a", action, "evidence-a", await executor.current_state_hash(action), "executor")
    )

    assert await adapter.get_query_settings_index_hint(Namespace("orders"), "shape-a") == QuerySettingsIndexHint(("customer_created",))
    rollback = await executor.rollback(QuerySettingsRollbackRequest("target-a", result.applied_entry.entry_id, "rollback"))

    assert rollback.forward_action["phase"] == "ROLLED_BACK"
    assert await adapter.get_query_settings_index_hint(Namespace("orders"), "shape-a") is None
    assert AppendOnlyLedger.verify(ledger.entries)


@pytest.mark.asyncio
async def test_existing_query_setting_requires_human_approval_and_restores_exact_prior_indexes() -> None:
    adapter, approvals, _, executor = await _executor()
    await adapter.set_query_settings_index_hint(Namespace("orders"), "shape-a", QuerySettingsIndexHint(("customer_created",)))
    action = _action(("customer_created",))
    request = QuerySettingsDeploymentRequest("target-a", "action-a", action, "evidence-a", await executor.current_state_hash(action), "executor", semi_autonomous=False)

    with pytest.raises(PermissionError, match="current approval required"):
        await executor.deploy(request)

    approval = approvals.request("action-a", "evidence-a")
    approvals.approve(approval.approval_id, "approver@example.test")
    result = await executor.deploy(request)
    await executor.rollback(QuerySettingsRollbackRequest("target-a", result.applied_entry.entry_id, "rollback"))

    assert await adapter.get_query_settings_index_hint(Namespace("orders"), "shape-a") == QuerySettingsIndexHint(("customer_created",))


@pytest.mark.asyncio
async def test_rollback_blocks_on_query_settings_drift() -> None:
    adapter, approvals, _, executor = await _executor()
    action = _action()
    approval = approvals.request("action-a", "evidence-a")
    approvals.approve(approval.approval_id, "approver@example.test")
    result = await executor.deploy(
        QuerySettingsDeploymentRequest("target-a", "action-a", action, "evidence-a", await executor.current_state_hash(action), "executor")
    )
    await adapter.set_query_settings_index_hint(Namespace("orders"), "shape-a", QuerySettingsIndexHint(("different",)))

    with pytest.raises(ProductionExecutionError, match="drift blocks exact rollback"):
        await executor.rollback(QuerySettingsRollbackRequest("target-a", result.applied_entry.entry_id, "rollback"))
