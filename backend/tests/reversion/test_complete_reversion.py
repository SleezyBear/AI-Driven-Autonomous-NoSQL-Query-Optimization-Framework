"""Phase 55 tests for S0 → S1 → S2 and exact, drift-safe reversion."""

from __future__ import annotations

import pytest

from app.actions.schemas import CreateIndexAction, IndexField, SetQuerySettingsIndexHintAction
from app.adapters.contracts import IndexSpec, Namespace
from app.adapters.fake import FakeDatabaseAdapter
from app.admission.models import AdmissionResult, AdmissionStatus, BenchmarkProfile
from app.approvals.flow import ApprovalFlow
from app.autonomy.policy import DeploymentMode
from app.ledger.chain import AppendOnlyLedger
from app.production.executor import DeploymentRequest, ProductionExecutor
from app.production.query_settings import (
    QuerySettingsDeploymentRequest,
    QuerySettingsExecutor,
    QuerySettingsRollbackRequest,
)
from app.reversion.fingerprint import optimizer_managed_fingerprint
from app.rollback.owned_index import OwnedIndexRollbacker, RollbackRequest, RollbackStatus


NAMESPACE = Namespace("orders")
SHAPE = "shape-demo"


def _index_action() -> CreateIndexAction:
    return CreateIndexAction(
        database="commerce",
        collection="orders",
        index_name="optimizer_customer",
        fields=(IndexField(field="customer_id", direction=1),),
    )


def _admission() -> AdmissionResult:
    return AdmissionResult(
        "candidate-1",
        "evaluation-1",
        BenchmarkProfile.AUTONOMOUS,
        "p95_latency_ms",
        10,
        10,
        AdmissionStatus.ADMITTED,
        (),
        production_eligible=True,
    )


@pytest.mark.asyncio
async def test_complete_reversion_restores_the_original_optimizer_managed_fingerprint() -> None:
    adapter = FakeDatabaseAdapter((NAMESPACE,))
    ledger = AppendOnlyLedger()
    index_executor = ProductionExecutor(adapter, ApprovalFlow(), ledger)
    settings_executor = QuerySettingsExecutor(adapter, ApprovalFlow(), ledger)
    original = await optimizer_managed_fingerprint(adapter, NAMESPACE, SHAPE)
    index_action = _index_action()

    index_result = await index_executor.deploy(
        DeploymentRequest(
            "target-a", "index-action", index_action, _admission(), "evidence-index",
            await index_executor.current_state_hash(index_action), "worker", DeploymentMode.FULL_AUTONOMOUS,
        )
    )
    state_s1 = await optimizer_managed_fingerprint(adapter, NAMESPACE, SHAPE)
    settings_action = SetQuerySettingsIndexHintAction(
        database="commerce",
        collection="orders",
        query_shape_hash=SHAPE,
        allowed_indexes=(index_action.index_name,),
    )
    settings_result = await settings_executor.deploy(
        QuerySettingsDeploymentRequest(
            "target-a", "settings-action", settings_action, "evidence-settings",
            await settings_executor.current_state_hash(settings_action), "worker", DeploymentMode.FULL_AUTONOMOUS,
        )
    )
    state_s2 = await optimizer_managed_fingerprint(adapter, NAMESPACE, SHAPE)

    await settings_executor.rollback(QuerySettingsRollbackRequest("target-a", settings_result.applied_entry.entry_id, "worker"))
    assert await optimizer_managed_fingerprint(adapter, NAMESPACE, SHAPE) == state_s1
    rollback = await OwnedIndexRollbacker(adapter, ledger).rollback(
        RollbackRequest("target-a", index_result.applied_entry.entry_id, "worker")
    )

    assert rollback.status is RollbackStatus.ROLLED_BACK
    assert state_s2 != state_s1 != original
    assert await optimizer_managed_fingerprint(adapter, NAMESPACE, SHAPE) == original
    assert AppendOnlyLedger.verify(ledger.entries)


@pytest.mark.asyncio
async def test_human_drift_blocks_automatic_index_rollback() -> None:
    adapter = FakeDatabaseAdapter((NAMESPACE,))
    ledger = AppendOnlyLedger()
    executor = ProductionExecutor(adapter, ApprovalFlow(), ledger)
    action = _index_action()
    deployed = await executor.deploy(
        DeploymentRequest(
            "target-a", "index-action", action, _admission(), "evidence-index",
            await executor.current_state_hash(action), "worker", DeploymentMode.FULL_AUTONOMOUS,
        )
    )
    await adapter.create_index(NAMESPACE, IndexSpec("human_drift", (("status", 1),)))

    result = await OwnedIndexRollbacker(adapter, ledger).rollback(
        RollbackRequest("target-a", deployed.applied_entry.entry_id, "worker")
    )

    assert result.status is RollbackStatus.ROLLBACK_BLOCKED
    assert "RELEVANT_DRIFT_DETECTED" in result.reason_codes
    assert {index.name for index in await adapter.list_indexes(NAMESPACE)} == {"optimizer_customer", "human_drift"}
