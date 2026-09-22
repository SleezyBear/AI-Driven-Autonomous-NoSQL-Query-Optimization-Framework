"""Durable, fail-closed experiment orchestration primitives for R28.

Every constituent (CommerceBench experiment, SafetyBench, NoSQLBench) has an
explicit state: PENDING, RUNNING, PASSED, FAILED, or INVALID.  A nonzero return
code is never recorded as success, and the top-level result fails if any
required constituent is not PASSED.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

AUTHORITATIVE_PYTHON_RELATIVE = "nosql/bin/python"
FORBIDDEN_INTERPRETER_MARKER = ".venv_r28"
REQUIRED_BENCH_ENV = ("JWT_SIGNING_KEY",)
INVALID_CLASSIFICATION = "INVALID_NONAUTHORITATIVE_R28_RUN"


class ConstituentState(str, Enum):
    """Explicit durable state for a constituent or the whole orchestration."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    INVALID = "INVALID"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def authoritative_python(root: Path) -> str:
    """Return the project-owned interpreter, refusing the ephemeral ``.venv_r28``."""
    interpreter = root / AUTHORITATIVE_PYTHON_RELATIVE
    if not interpreter.exists():
        raise RuntimeError(f"authoritative project interpreter is missing: {interpreter}")
    return str(interpreter)


def is_authoritative_interpreter(command: Sequence[str]) -> bool:
    """Whether every Python-looking token in a command is project-owned."""
    joined = " ".join(command)
    if FORBIDDEN_INTERPRETER_MARKER in joined:
        return False
    return True


@dataclass
class Constituent:
    """Durable record of one required piece of evidence."""

    name: str
    kind: str
    required: bool = True
    command: tuple[str, ...] = ()
    status: ConstituentState = ConstituentState.PENDING
    returncode: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    stdout_log: str | None = None
    stderr_log: str | None = None
    evidence: str | None = None
    failure_reason: str | None = None
    profile: str | None = None
    mode: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["command"] = list(self.command)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "Constituent":
        data = dict(payload)
        data["status"] = ConstituentState(str(data.get("status", ConstituentState.PENDING.value)))
        raw_command = data.get("command")
        command = raw_command if isinstance(raw_command, (list, tuple)) else ()
        data["command"] = tuple(str(token) for token in command)
        return cls(**data)  # type: ignore[arg-type]


def status_for_returncode(returncode: int | None, *, evidence_present: bool) -> ConstituentState:
    """Map a process outcome to an explicit state; nonzero is never success."""
    if returncode is None:
        return ConstituentState.PENDING
    if returncode != 0:
        return ConstituentState.FAILED
    return ConstituentState.PASSED if evidence_present else ConstituentState.FAILED


def overall_status(constituents: Sequence[Constituent]) -> ConstituentState:
    """Top-level state: any required constituent not PASSED fails the whole run."""
    required = [item for item in constituents if item.required]
    if not required:
        return ConstituentState.PENDING
    if any(item.status is ConstituentState.INVALID for item in required):
        return ConstituentState.FAILED
    if all(item.status is ConstituentState.PASSED for item in required):
        return ConstituentState.PASSED
    if any(item.status is ConstituentState.FAILED for item in required):
        return ConstituentState.FAILED
    return ConstituentState.RUNNING


def is_authoritative_pass(manifest: Mapping[str, object]) -> bool:
    """Whether an existing manifest is a completed authoritative PASS.

    Invalidated, failed, or pending evidence is never treated as complete.
    """
    if str(manifest.get("classification", "")) == INVALID_CLASSIFICATION:
        return False
    return str(manifest.get("status", "")) == ConstituentState.PASSED.value


def require_environment(environment: Mapping[str, str], required: Sequence[str] = REQUIRED_BENCH_ENV) -> None:
    """Fail closed when a required secret is absent; never disable the requirement."""
    missing = [name for name in required if not environment.get(name)]
    if missing:
        raise RuntimeError(f"required environment is missing (fail-closed): {sorted(missing)}")


def provision_bench_environment(*, secret_dir: Path, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Create a disposable, experiment-owned, fail-closed benchmark environment.

    Generates a fresh JWT signing key and control-plane master key file for
    this experiment only.  It never reads, modifies, or logs development
    secrets.
    """
    environment = dict(base if base is not None else os.environ)
    secret_dir.mkdir(parents=True, exist_ok=True)
    master_key = secret_dir / "control_plane_master_key"
    if not master_key.exists():
        master_key.write_bytes(os.urandom(32))
        master_key.chmod(0o400)
    replica_key = secret_dir / "mongodb_replica_keyfile"
    if not replica_key.exists():
        replica_key.write_bytes(os.urandom(512))
        replica_key.chmod(0o400)
    environment.setdefault("JWT_SIGNING_KEY", os.urandom(32).hex())
    environment["CONTROL_PLANE_MASTER_KEY_FILE"] = str(master_key)
    environment["MONGODB_REPLICA_KEYFILE"] = str(replica_key)
    environment.setdefault("APP_ENV", "test")
    require_environment(environment)
    return environment


def run_command(command: Sequence[str], *, environment: Mapping[str, str] | None = None) -> tuple[int, str, str]:
    """Run a command, capturing stdout/stderr without a shell."""
    completed = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        env=dict(environment) if environment is not None else None,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def write_json(path: Path, payload: object) -> None:
    """Atomically write JSON so interrupted runs never leave partial evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> dict[str, object]:
    document: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return document


def disposable_secret_dir() -> Path:
    """Create an experiment-owned temporary secret directory."""
    return Path(tempfile.mkdtemp(prefix="r28-secrets-"))


def discard_secret_dir(path: Path) -> None:
    """Remove a disposable secret directory, refusing anything outside the temp root."""
    root = Path(tempfile.gettempdir())
    resolved = path.resolve()
    if root in resolved.parents and resolved.name.startswith("r28-secrets-"):
        shutil.rmtree(resolved, ignore_errors=True)
