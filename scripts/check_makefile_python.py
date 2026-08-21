"""Ensure Makefile Python invocations cannot escape the project-owned venv."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / "Makefile"
PYTHON_COMMAND = re.compile(r"(?:^|\s)(?:python(?:\d+(?:\.\d+)*)?|pytest|ruff|mypy)(?:\s|$)")


def main() -> int:
    """Fail if a recipe invokes a Python tool without $(PYTHON)."""
    failures = [
        f"line {line_number}: {line.strip()}"
        for line_number, line in enumerate(MAKEFILE.read_text(encoding="utf-8").splitlines(), start=1)
        if line.startswith("\t") and PYTHON_COMMAND.search(line) and "$(PYTHON)" not in line
    ]
    if failures:
        print("Makefile Python environment boundary: FAIL", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("Makefile Python environment boundary: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
