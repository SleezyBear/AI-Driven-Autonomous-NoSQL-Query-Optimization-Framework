"""Exercise the real Compose worker container without touching database volumes."""

from __future__ import annotations

import json
import subprocess


COMPOSE = ["docker", "compose", "--profile", "light"]


def run(*arguments: str) -> str:
    return subprocess.run([*COMPOSE, *arguments], check=True, text=True, capture_output=True).stdout


def inspect(container_id: str) -> dict[str, object]:
    return json.loads(subprocess.run(["docker", "inspect", container_id], check=True, text=True, capture_output=True).stdout)[0]


def worker_container_id() -> str:
    return run("ps", "-q", "worker").strip()


def main() -> int:
    run("up", "-d", "--build", "--wait", "worker")
    first_id = worker_container_id()
    if not first_id:
        raise RuntimeError("worker container is not running")
    first = inspect(first_id)
    config = first["Config"]
    host_config = first["HostConfig"]
    state = first["State"]
    command = " ".join(config.get("Cmd") or [])  # type: ignore[union-attr]
    if "app.worker.service" not in command:
        raise RuntimeError("worker container does not invoke app.worker.service")
    if state.get("Health", {}).get("Status") != "healthy":  # type: ignore[union-attr]
        raise RuntimeError("worker durable PostgreSQL readiness healthcheck is not healthy")
    if host_config.get("PortBindings"):
        raise RuntimeError("worker must not publish a public port")
    if host_config.get("RestartPolicy", {}).get("Name") != "unless-stopped":  # type: ignore[union-attr]
        raise RuntimeError("worker restart policy is not unless-stopped")
    if config.get("StopTimeout") != 45:  # type: ignore[union-attr]
        raise RuntimeError("worker stop grace period is not 45 seconds")
    first_logs = run("logs", "--no-log-prefix", "worker")
    if "worker_started" not in first_logs or "worker_id=" not in first_logs:
        raise RuntimeError("worker did not enter the real polling service")

    run("stop", "worker")
    stopped = inspect(first_id)
    if stopped["State"].get("ExitCode") != 0:  # type: ignore[union-attr]
        raise RuntimeError("worker did not exit cleanly after Compose SIGTERM")
    stopped_logs = run("logs", "--no-log-prefix", "worker")
    if "worker_stopping" not in stopped_logs:
        raise RuntimeError("worker did not record its graceful shutdown path")

    run("up", "-d", "--wait", "worker")
    restarted_logs = run("logs", "--no-log-prefix", "worker")
    ids = {line.split("worker_id=", 1)[1].split()[0] for line in restarted_logs.splitlines() if "worker_started" in line and "worker_id=" in line}
    if len(ids) < 2:
        raise RuntimeError("worker restart did not create a new unique worker identity")
    print("R19C Docker worker verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
