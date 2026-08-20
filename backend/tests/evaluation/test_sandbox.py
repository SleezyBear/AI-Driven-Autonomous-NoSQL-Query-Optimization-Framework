"""Phase 20 acceptance tests for evaluation-target-only candidate execution."""

import pytest

from app.actions.schemas import CreateIndexAction
from app.adapters.contracts import Namespace
from app.adapters.fake import FakeDatabaseAdapter
from app.evaluation.sandbox import EvaluationState, ResourceBudget, SandboxIndexEvaluator, SandboxStatus


class Copier:
    async def copy_and_verify(self, monitored_target_id: str, evaluation_target_id: str) -> EvaluationState:
        return EvaluationState("dataset", "dataset", f"topology-{monitored_target_id}", f"topology-{evaluation_target_id}", 1000)


class UnsafeCopier:
    async def copy_and_verify(self, monitored_target_id: str, evaluation_target_id: str) -> EvaluationState:
        return EvaluationState("dataset", "dataset", "same-topology", "same-topology", 1000)


def _candidate() -> CreateIndexAction:
    return CreateIndexAction(database="commerce", collection="orders", index_name="candidate", fields=({"field": "customer_id", "direction": 1},))


@pytest.mark.asyncio
async def test_candidate_runs_only_on_evaluation_target_and_is_cleaned_up() -> None:
    monitored = FakeDatabaseAdapter()
    evaluation = FakeDatabaseAdapter()
    evaluator = SandboxIndexEvaluator(Copier(), evaluation)

    result = await evaluator.evaluate("monitored", "evaluation", _candidate(), ResourceBudget(500, 100), lambda _: 10, _benchmark, lambda result: f"admit:{result}")

    assert result.status == SandboxStatus.COMPLETED
    assert result.admission_result == "admit:benchmark"
    assert await monitored.list_indexes(Namespace(collection="orders")) == ()
    assert await evaluation.list_indexes(Namespace(collection="orders")) == ()


@pytest.mark.asyncio
async def test_same_target_or_budget_violation_never_applies_candidate() -> None:
    evaluation = FakeDatabaseAdapter()
    evaluator = SandboxIndexEvaluator(Copier(), evaluation)

    same_target = await evaluator.evaluate("same", "same", _candidate(), ResourceBudget(500, 100), lambda _: 10, _benchmark, str)
    over_budget = await evaluator.evaluate("monitored", "evaluation", _candidate(), ResourceBudget(5, 100), lambda _: 10, _benchmark, str)

    assert same_target.status == SandboxStatus.REJECTED_TARGET_SEPARATION
    assert over_budget.status == SandboxStatus.REJECTED_RESOURCE_BUDGET
    assert await evaluation.list_indexes(Namespace(collection="orders")) == ()


@pytest.mark.asyncio
async def test_identical_connection_identity_is_rejected_before_candidate_application() -> None:
    evaluation = FakeDatabaseAdapter()
    evaluator = SandboxIndexEvaluator(UnsafeCopier(), evaluation)

    result = await evaluator.evaluate("monitored", "evaluation", _candidate(), ResourceBudget(500, 100), lambda _: 10, _benchmark, str)

    assert result.status == SandboxStatus.INVALID_EVALUATION_STATE
    assert await evaluation.list_indexes(Namespace(collection="orders")) == ()


@pytest.mark.asyncio
async def test_cleanup_runs_when_benchmark_fails() -> None:
    evaluation = FakeDatabaseAdapter()
    evaluator = SandboxIndexEvaluator(Copier(), evaluation)

    result = await evaluator.evaluate("monitored", "evaluation", _candidate(), ResourceBudget(500, 100), lambda _: 10, _failing_benchmark, str)

    assert result.status == SandboxStatus.FAILED
    assert await evaluation.list_indexes(Namespace(collection="orders")) == ()


async def _benchmark() -> str:
    return "benchmark"


async def _failing_benchmark() -> str:
    raise RuntimeError("benchmark failure")
