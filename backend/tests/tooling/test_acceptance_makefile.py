"""Phase 56 checks for the final acceptance command contract."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_makefile_routes_python_recipes_through_the_project_venv() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_makefile_python.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "Makefile Python environment boundary: PASS"


def test_full_acceptance_target_contains_every_required_final_gate() -> None:
    content = (ROOT / "Makefile").read_text(encoding="utf-8")
    acceptance = content[content.index("acceptance:") : content.index("nosqlbench-smoke:")]

    for required in (
        "scripts/verify_environment.py",
        "$(PIP) check",
        "scripts/check_python_dependencies.py",
        "-m pytest backend/tests",
        "-m ruff check",
        "-m mypy",
        "-m alembic",
        "backend/tests/adapters",
        "test_executor_permissions.py",
        "backend/tests/unit/admission",
        "backend/tests/ledger",
        "backend/tests/security",
        "node:22.14.0-alpine npm test",
        "playwright",
        "backend/tests/commercebench",
        "nosqlbench-smoke",
        "backend/tests/safetybench",
        "backend/tests/rollback backend/tests/reversion",
        "backend/tests/ai",
        "phase47-acceptance",
    ):
        assert required in acceptance
