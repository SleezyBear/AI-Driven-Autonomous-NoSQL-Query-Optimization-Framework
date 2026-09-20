"""Capture safe, deterministic build provenance without environment values."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "generated" / "provenance.json"


def _command(*arguments: str) -> str:
    return subprocess.check_output(arguments, cwd=ROOT, text=True).strip()


def main() -> int:
    requirements = ROOT / "requirements.txt"
    production_requirements = ROOT / "requirements.production.in"
    package_lock = ROOT / "frontend" / "package-lock.json"
    dirty = bool(_command("git", "status", "--porcelain"))
    document = {
        "schema": "nosql-optimizer-build-provenance/v1",
        "git_revision": _command("git", "rev-parse", "HEAD"),
        "dirty": dirty,
        "python": platform.python_version(),
        "node": os.getenv("BUILD_NODE_VERSION") or _command("node", "--version"),
        "dependency_locks": {
            "requirements.txt": hashlib.sha256(requirements.read_bytes()).hexdigest(),
            "requirements.production.in": hashlib.sha256(
                production_requirements.read_bytes()
            ).hexdigest(),
            "frontend/package-lock.json": hashlib.sha256(package_lock.read_bytes()).hexdigest(),
        },
        "build_commands": ["python -m pip install -r requirements.txt", "npm ci", "npm run build"],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("BUILD PROVENANCE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
