"""Phase 53 acceptance tests for the four-command demonstration lifecycle."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "demo_mode.py"


def test_demo_commands_show_the_complete_safe_lifecycle(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    for command in ("reset", "start", "seed"):
        completed = _run(command, state)
        assert completed.returncode == 0, completed.stderr
    completed = _run("workload", state)

    assert completed.returncode == 0, completed.stderr
    assert "slow workload\n→ diagnose\n→ candidate\n→ sandbox" in completed.stdout
    assert "→ rollback" in completed.stdout
    persisted = json.loads(state.read_text())
    assert persisted["status"] == "COMPLETED"
    assert persisted["summary"] == {
        "admission": "ADMITTED",
        "approval": "APPROVED",
        "ledger_entries": 3,
        "rollback": "ROLLED_BACK",
        "sandbox": "COMPLETED",
    }


def test_demo_enforces_command_order(tmp_path: Path) -> None:
    completed = _run("workload", tmp_path / "state.json")

    assert completed.returncode != 0
    assert "run demo-reset first" in completed.stderr


def _run(command: str, state: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), command, "--state", str(state)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
