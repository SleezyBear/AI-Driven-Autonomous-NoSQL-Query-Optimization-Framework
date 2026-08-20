"""Integration test for the executor credential's document-mutation boundary."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_executor_cannot_modify_application_documents() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/verify_mongodb_permissions.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "MongoDB executor permission boundary: PASS" in result.stdout

