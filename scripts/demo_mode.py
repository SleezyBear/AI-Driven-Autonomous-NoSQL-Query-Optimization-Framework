"""Safe deterministic demonstration of the complete optimizer decision lifecycle."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.actions.schemas import CreateIndexAction, IndexField  # noqa: E402
from app.adapters.contracts import Namespace  # noqa: E402
from app.adapters.fake import FakeDatabaseAdapter  # noqa: E402
from app.admission.models import (  # noqa: E402
    AdmissionRequest,
    BenchmarkProfile,
    MetricEvaluationInput,
)
from app.admission.policy import DEFAULT_POLICIES  # noqa: E402
from app.admission.statistics import evaluate_candidate_admission  # noqa: E402
from app.approvals.flow import ApprovalFlow  # noqa: E402
from app.evaluation.sandbox import (  # noqa: E402
    EvaluationState,
    ResourceBudget,
    SandboxIndexEvaluator,
)
from app.ledger.chain import AppendOnlyLedger  # noqa: E402
from app.production.executor import DeploymentRequest, ProductionExecutor  # noqa: E402
from app.rollback.owned_index import OwnedIndexRollbacker, RollbackRequest  # noqa: E402


DEFAULT_STATE = ROOT / ".demo" / "state.json"
_FLOW = (
    "slow workload",
    "diagnose",
    "candidate",
    "sandbox",
    "statistical admission",
    "approval",
    "deploy",
    "measure",
    "ledger",
    "rollback",
)


class DemoStateCopier:
    """Provide verified, non-production demo state to the real sandbox evaluator."""

    async def copy_and_verify(self, monitored_target_id: str, evaluation_target_id: str) -> EvaluationState:
        return EvaluationState("demo-data", "demo-data", monitored_target_id, evaluation_target_id, 1_000_000)


def main() -> int:
    """Execute one stateful demo command."""
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("reset", "start", "seed", "workload"))
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args()
    if args.command == "reset":
        _write_state(args.state, {"status": "RESET", "events": []})
        print("demo reset")
    elif args.command == "start":
        _transition(args.state, "RESET", "STARTED", "demo-start")
    elif args.command == "seed":
        _transition(args.state, "STARTED", "SEEDED", "demo-seed")
    else:
        asyncio.run(_run_workload(args.state))
    return 0


def _transition(path: Path, expected: str, next_status: str, event: str) -> None:
    state = _read_state(path)
    if state["status"] != expected:
        raise RuntimeError(f"demo must be {expected.lower()} before this command")
    state["status"] = next_status
    events = state["events"]
    if not isinstance(events, list):
        raise RuntimeError("demo state is malformed; run demo-reset")
    events.append(event)
    _write_state(path, state)
    print(event)


async def _run_workload(path: Path) -> None:
    state = _read_state(path)
    if state["status"] != "SEEDED":
        raise RuntimeError("demo must be seeded before workload execution")

    action = CreateIndexAction(database="demo", collection="orders", index_name="optimizer_demo_status", fields=(IndexField(field="status", direction=1),))
    evaluation_adapter = FakeDatabaseAdapter((Namespace("orders"),))
    sandbox = SandboxIndexEvaluator(DemoStateCopier(), evaluation_adapter)
    sandbox_result = await sandbox.evaluate(
        "demo-monitored",
        "demo-evaluation",
        action,
        ResourceBudget(1_000, 1_000),
        lambda _: 100,
        _benchmark,
        lambda measurement: measurement,
    )
    if sandbox_result.benchmark_result != "candidate-p95=80ms":
        raise RuntimeError("demo sandbox did not produce its deterministic measurement")

    admission = evaluate_candidate_admission(
        AdmissionRequest(
            "demo-candidate",
            "demo-run",
            BenchmarkProfile.AUTONOMOUS,
            "p95_latency_ms",
            (
                MetricEvaluationInput(
                    "p95_latency_ms",
                    "GLOBAL",
                    "all",
                    DEFAULT_POLICIES["p95_latency_ms"],
                    (100.0,) * 10,
                    (80.0,) * 10,
                    aa_scores=(0.0,) * 10,
                ),
            ),
        )
    )
    if not admission.production_eligible:
        raise RuntimeError("demo statistical admission did not produce production-eligible evidence")

    production_adapter = FakeDatabaseAdapter((Namespace("orders"),))
    approvals = ApprovalFlow()
    ledger = AppendOnlyLedger()
    executor = ProductionExecutor(production_adapter, approvals, ledger)
    evidence_hash = "demo-evidence-v1"
    approval = approvals.request("demo-action", evidence_hash, "demo-monitored")
    approvals.approve(approval.approval_id, "demo-approver")
    deployment = await executor.deploy(
        DeploymentRequest(
            "demo-monitored",
            "demo-action",
            action,
            admission,
            evidence_hash,
            await executor.current_state_hash(action),
            "demo-operator",
        )
    )
    rollback = await OwnedIndexRollbacker(production_adapter, ledger).rollback(
        RollbackRequest("demo-monitored", deployment.applied_entry.entry_id, "demo-operator")
    )
    if rollback.ledger_entry is None:
        raise RuntimeError("demo rollback did not complete")

    state["status"] = "COMPLETED"
    events = state["events"]
    if not isinstance(events, list):
        raise RuntimeError("demo state is malformed; run demo-reset")
    events.extend(_FLOW)
    state["summary"] = {
        "sandbox": sandbox_result.status.value,
        "admission": admission.status.value,
        "approval": approvals.get(approval.approval_id).status.value,
        "ledger_entries": len(ledger.entries),
        "rollback": rollback.status.value,
    }
    _write_state(path, state)
    print("\n→ ".join(_FLOW))
    print(json.dumps(state["summary"], sort_keys=True))


async def _benchmark() -> str:
    return "candidate-p95=80ms"


def _read_state(path: Path) -> dict[str, object]:
    if not path.exists():
        raise RuntimeError("run demo-reset first")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("status"), str) or not isinstance(value.get("events"), list):
        raise RuntimeError("demo state is malformed; run demo-reset")
    return value


def _write_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
