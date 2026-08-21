"""Ensure every historical SYSTEM_PASS is backed by registered system evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS = PROJECT_ROOT / "docs" / "PHASE_STATUS.md"
DEFAULT_REGISTRY = PROJECT_ROOT / "docs" / "SYSTEM_ACCEPTANCE_REGISTRY.json"
SYSTEM_PASS_ROW = re.compile(r"^\|\s*(?P<phase>\d+)\s*\|.*\bSYSTEM_PASS\b.*\|", re.MULTILINE)


def system_pass_phases(status_path: Path) -> set[str]:
    return {match.group("phase") for match in SYSTEM_PASS_ROW.finditer(status_path.read_text())}


def registered_phases(registry_path: Path) -> set[str]:
    data = json.loads(registry_path.read_text())
    entries = data.get("system_acceptance_tests")
    if not isinstance(entries, list):
        raise ValueError("system_acceptance_tests must be a JSON list")

    phases: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("each system acceptance entry must be an object")
        phase = entry.get("phase")
        command = entry.get("command")
        test = entry.get("test")
        if not all(isinstance(value, str) and value.strip() for value in (phase, command, test)):
            raise ValueError("each entry requires non-empty phase, command, and test strings")
        phases.add(phase)
    return phases


def check(status_path: Path, registry_path: Path) -> int:
    try:
        missing = system_pass_phases(status_path) - registered_phases(registry_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"System-pass registry: FAIL — {error}")
        return 1
    if missing:
        print(f"System-pass registry: FAIL — missing registrations for phase(s): {', '.join(sorted(missing, key=int))}")
        return 1
    print(f"System-pass registry: PASS ({len(system_pass_phases(status_path))} SYSTEM_PASS phase(s) registered)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    arguments = parser.parse_args()
    return check(arguments.phase_status, arguments.registry)


if __name__ == "__main__":
    raise SystemExit(main())
