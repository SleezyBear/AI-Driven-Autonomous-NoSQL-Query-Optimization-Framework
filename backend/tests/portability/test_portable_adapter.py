"""Phase 47 proof that core orchestration works with a portable typed adapter."""

import subprocess
import sys
from pathlib import Path

import pytest

from app.actions.schemas import CreateIndexAction, IndexField
from app.adapters.contracts import Namespace
from app.adapters.fake_portable import FakePortableAdapter
from app.evaluation.sandbox import EvaluationState, ResourceBudget, SandboxIndexEvaluator, SandboxStatus


ROOT = Path(__file__).resolve().parents[3]


class PortableStateCopier:
    """Portable test double for the state-copy boundary."""

    async def copy_and_verify(self, monitored_target_id: str, evaluation_target_id: str) -> EvaluationState:
        assert (monitored_target_id, evaluation_target_id) == ("source", "evaluation")
        return EvaluationState("dataset", "dataset", "source-topology", "evaluation-topology", 1_000)


@pytest.mark.asyncio
async def test_core_sandbox_orchestration_runs_through_fake_portable_adapter() -> None:
    adapter = FakePortableAdapter((Namespace("orders"),))
    evaluator = SandboxIndexEvaluator(PortableStateCopier(), adapter)
    candidate = CreateIndexAction(database="commerce", collection="orders", index_name="customer_created", fields=(IndexField(field="customer_id", direction=1),))

    result = await evaluator.evaluate("source", "evaluation", candidate, ResourceBudget(100, 100), lambda _: 10, _benchmark, lambda measurement: f"admitted:{measurement}")

    assert result.status is SandboxStatus.COMPLETED
    assert result.admission_result == "admitted:portable-measurement"
    assert adapter.operations == [("create_index", "orders", "customer_created"), ("drop_index", "orders", "customer_created")]
    assert await adapter.list_indexes(Namespace("orders")) == ()


def test_core_app_import_boundary_and_portability_checker_are_clean() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_database_portability.py"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "Database portability import boundary: PASS"


async def _benchmark() -> str:
    return "portable-measurement"
