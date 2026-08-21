from __future__ import annotations

import json
from pathlib import Path

from scripts.check_system_pass_registry import check


def write_status(path: Path, status: str) -> None:
    path.write_text(
        "| Phase | Scope | Status | Observable test |\n"
        "| --- | --- | --- | --- |\n"
        f"| 7 | test | {status} | `make system` |\n"
    )


def test_repository_registry_matches_current_status() -> None:
    root = Path(__file__).resolve().parents[3]
    assert check(root / "docs" / "PHASE_STATUS.md", root / "docs" / "SYSTEM_ACCEPTANCE_REGISTRY.json") == 0


def test_system_pass_requires_registered_system_acceptance(tmp_path: Path) -> None:
    status = tmp_path / "status.md"
    registry = tmp_path / "registry.json"
    write_status(status, "HISTORICAL — SYSTEM_PASS")
    registry.write_text(json.dumps({"system_acceptance_tests": []}))

    assert check(status, registry) == 1


def test_registered_system_pass_is_accepted(tmp_path: Path) -> None:
    status = tmp_path / "status.md"
    registry = tmp_path / "registry.json"
    write_status(status, "HISTORICAL — SYSTEM_PASS")
    registry.write_text(
        json.dumps(
            {
                "system_acceptance_tests": [
                    {"phase": "7", "command": "make system", "test": "backend/tests/system/test_real_flow.py"}
                ]
            }
        )
    )

    assert check(status, registry) == 0
