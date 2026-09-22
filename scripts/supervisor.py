#!/usr/bin/env python3
"""Launch the authoritative R28 orchestrator sequentially.

The orchestrator already schedules SafetyBench, NoSQLBench, STANDARD, and
PUBLICATION in one fail-closed, resumable pass.  This supervisor simply runs
that pass with the project-owned interpreter and records the action.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "artifacts/experiments/supervisor.log"


def append(message: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")
    print(message)


def main() -> int:
    python = str(ROOT / "nosql/bin/python")
    mongo_uri = os.environ.get("MONGO_URI") or "mongodb://control_plane_root:control_plane_root_dev_only@127.0.0.1:27018/?authSource=admin&directConnection=true"
    command = [
        python,
        "scripts/experiment_orchestrator.py",
        "--mongo-uri",
        mongo_uri,
        "--run-safetybench",
        "--run-nosqlbench",
        "--run-standard",
        "--run-publication",
    ]
    append(f"Launching authoritative orchestrator: {' '.join(command)}")
    completed = subprocess.run(command, cwd=ROOT, check=False)
    append(f"Orchestrator exited rc={completed.returncode}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
