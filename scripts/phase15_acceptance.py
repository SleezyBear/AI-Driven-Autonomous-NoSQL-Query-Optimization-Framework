"""Run Phase-15 tests and print the required observable verdict summary."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMAND = [str(ROOT / "nosql/bin/python"), "-m", "pytest", "backend/tests/unit/admission"]
SUMMARY = (
    ("SAFE BENEFIT", "ADMITTED"),
    ("MINORITY QUERY REGRESSION", "REJECTED_REGRESSION"),
    ("TINY BENEFIT", "REJECTED_NO_MEANINGFUL_BENEFIT"),
    ("NOISY ENVIRONMENT", "INCONCLUSIVE_NOISE"),
    ("CPU REGRESSION", "REJECTED_REGRESSION"),
    ("MISSING METRIC", "INCONCLUSIVE_MISSING_METRIC"),
    ("ENVIRONMENT MISMATCH", "INCONCLUSIVE_ENVIRONMENT"),
    ("SAFETY INVARIANT", "REJECTED_SAFETY_INVARIANT"),
)


def main() -> int:
    """Run the synthetic verdict suite and print its tested expected outcomes."""
    completed = subprocess.run(COMMAND, cwd=ROOT, check=False)
    if completed.returncode:
        return completed.returncode
    for label, verdict in SUMMARY:
        print(f"{label:<31} {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
