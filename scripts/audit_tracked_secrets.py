"""Reject obvious secret material in Git-tracked project configuration without printing it."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_FILENAMES = {".env", "control_plane_master_key", "mongodb_replica_keyfile"}
SENSITIVE_MARKERS = ("BEGIN PRIVATE KEY", "mongodb://")


def main() -> int:
    """Inspect tracked paths and configuration content while keeping sensitive values private."""
    tracked = subprocess.check_output(["git", "ls-files"], cwd=REPOSITORY_ROOT, text=True).splitlines()
    failures: list[str] = []
    for relative_path in tracked:
        path = Path(relative_path)
        if path.name in SENSITIVE_FILENAMES or relative_path.startswith("nosql/"):
            failures.append(relative_path)
            continue
        if relative_path.startswith("backend/tests/") or relative_path.startswith("scripts/"):
            continue
        if path.suffix not in {".env", ".example", ".yml", ".yaml", ".json", ".toml"}:
            continue
        try:
            content = (REPOSITORY_ROOT / path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(marker in content for marker in SENSITIVE_MARKERS):
            failures.append(relative_path)
    if failures:
        print("TRACKED SECRET AUDIT: FAIL (sensitive tracked paths detected)")
        return 1
    print("TRACKED SECRET AUDIT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
