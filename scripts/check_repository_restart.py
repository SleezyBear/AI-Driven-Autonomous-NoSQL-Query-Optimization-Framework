"""Verify real control-plane state survives API/worker process restarts."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.runtime import create_control_plane_repositories  # noqa: E402
from app.worker.durable import JobRepository  # noqa: E402


async def write_state(state_file: Path) -> None:
    engine, repositories = create_control_plane_repositories()
    durable_jobs = JobRepository(engine)
    try:
        user = await repositories.users.create(email="r3@example.test", password_hash="r3", status="ACTIVE", failed_login_count=0)
        target = await repositories.targets.create(
            owner_user_id=user["id"], name="r3-target", deployment_mode="APPROVAL_CONTROLLED",
            state="ACTIVE", connection_label="r3", is_active=True,
        )
        setting = await repositories.settings.create(scope="r3", key="restart-proof", value={"target_id": str(target["id"])})
        job_id = await durable_jobs.enqueue({"kind": "R3_RESTART_PROOF", "target_id": str(target["id"])})
        state_file.write_text(json.dumps({"user": str(user["id"]), "target": str(target["id"]), "setting": str(setting["id"]), "job": job_id}))
    finally:
        await engine.dispose()


async def verify_and_cleanup(state_file: Path) -> None:
    state = json.loads(state_file.read_text())
    engine, repositories = create_control_plane_repositories()
    durable_jobs = JobRepository(engine)
    try:
        assert await repositories.users.get(state["user"])
        assert await repositories.targets.get(state["target"])
        assert await repositories.settings.get(state["setting"])
        claimed = await durable_jobs.claim("r3-restarted-worker")
        assert claimed is not None and claimed.id == state["job"]
        assert await durable_jobs.complete(claimed.id, "r3-restarted-worker")
        await repositories.jobs.delete(state["job"])
        await repositories.settings.delete(state["setting"])
        await repositories.targets.delete(state["target"])
        await repositories.users.delete(state["user"])
    finally:
        await engine.dispose()
        state_file.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("write", "verify"))
    parser.add_argument("--state-file", type=Path, required=True)
    arguments = parser.parse_args()
    asyncio.run(write_state(arguments.state_file) if arguments.mode == "write" else verify_and_cleanup(arguments.state_file))
    print(f"Repository restart check ({arguments.mode}): PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
