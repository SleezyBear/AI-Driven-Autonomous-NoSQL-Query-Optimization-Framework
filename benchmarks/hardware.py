"""Mandatory host and runtime manifests for reproducible benchmark artifacts."""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass
from importlib.metadata import version
from typing import Protocol


@dataclass(frozen=True)
class HardwareManifest:
    """The complete host, container, database, and model identity for one benchmark."""

    macos_version: str
    cpu_model: str
    architecture: str
    physical_cores: int
    logical_cpus: int
    ram_bytes: int
    docker_version: str
    docker_allocated_cpus: int
    docker_allocated_ram_bytes: int
    mongodb_version: str
    postgresql_version: str
    python_version: str
    numpy_version: str
    scipy_version: str
    pymongo_version: str
    ollama_version: str
    chat_model: str
    embedding_model: str


class HardwareManifestCollector(Protocol):
    """Capture a complete manifest before any controlled benchmark measurements."""

    def collect(self) -> HardwareManifest:
        """Return every mandatory reproducibility field or fail closed."""


class CommandRunner(Protocol):
    """Run one local diagnostic command and return its non-empty stdout."""

    def run(self, *command: str) -> str:
        """Run a command without accepting shell input."""


class SubprocessCommandRunner:
    """Safe command adapter for the supported local development topology."""

    def run(self, *command: str) -> str:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        output = completed.stdout.strip()
        if not output:
            raise RuntimeError(f"command produced no output: {' '.join(command)}")
        return output


class SystemHardwareManifestCollector:
    """Collect the Phase 51 manifest from the host and light Docker topology."""

    def __init__(self, runner: CommandRunner | None = None, environment: dict[str, str] | None = None) -> None:
        self._runner = runner or SubprocessCommandRunner()
        self._environment = environment if environment is not None else dict(os.environ)

    def collect(self) -> HardwareManifest:
        """Fail closed when any mandatory reproducibility fact cannot be determined."""
        logical_cpus = os.cpu_count()
        if logical_cpus is None:
            raise RuntimeError("logical CPU count is unavailable")
        return HardwareManifest(
            macos_version=self._runner.run("sw_vers", "-productVersion"),
            cpu_model=self._runner.run("sysctl", "-n", "machdep.cpu.brand_string"),
            architecture=platform.machine(),
            physical_cores=int(self._runner.run("sysctl", "-n", "hw.physicalcpu")),
            logical_cpus=logical_cpus,
            ram_bytes=int(self._runner.run("sysctl", "-n", "hw.memsize")),
            docker_version=self._runner.run("docker", "version", "--format", "{{.Server.Version}}"),
            docker_allocated_cpus=int(self._runner.run("docker", "info", "--format", "{{.NCPU}}")),
            docker_allocated_ram_bytes=int(self._runner.run("docker", "info", "--format", "{{.MemTotal}}")),
            mongodb_version=self._runner.run(
                "docker", "compose", "--profile", "light", "exec", "-T", "mongo-monitored", "mongosh", "--quiet", "--eval", "db.version()"
            ),
            postgresql_version=self._runner.run(
                "docker", "compose", "--profile", "light", "exec", "-T", "postgres", "psql", "-U", "control_plane", "-d", "control_plane", "-tAc", "SHOW server_version"
            ),
            python_version=platform.python_version(),
            numpy_version=version("numpy"),
            scipy_version=version("scipy"),
            pymongo_version=version("pymongo"),
            ollama_version=self._runner.run("ollama", "--version"),
            chat_model=self._environment.get("OLLAMA_CHAT_MODEL", "gemma4:e4b"),
            embedding_model=self._environment.get("OLLAMA_EMBEDDING_MODEL", "embeddinggemma"),
        )
