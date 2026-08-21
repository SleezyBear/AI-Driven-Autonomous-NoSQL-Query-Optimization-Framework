"""Phase 51 acceptance tests for mandatory benchmark hardware manifests."""

from __future__ import annotations

from benchmarks.hardware import HardwareManifest, SystemHardwareManifestCollector


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.responses = {
            ("sw_vers", "-productVersion"): "15.7.7",
            ("sysctl", "-n", "machdep.cpu.brand_string"): "Intel Core i7-8850H",
            ("sysctl", "-n", "hw.physicalcpu"): "6",
            ("sysctl", "-n", "hw.memsize"): "17179869184",
            ("docker", "version", "--format", "{{.Server.Version}}") : "28.0.0",
            ("docker", "info", "--format", "{{.NCPU}}") : "6",
            ("docker", "info", "--format", "{{.MemTotal}}") : "8589934592",
            (
                "docker", "compose", "--profile", "light", "exec", "-T", "mongo-monitored",
                "mongosh", "--quiet", "--eval", "db.version()",
            ): "8.0.0",
            (
                "docker", "compose", "--profile", "light", "exec", "-T", "postgres", "psql",
                "-U", "control_plane", "-d", "control_plane", "-tAc", "SHOW server_version",
            ): "17.0",
            ("ollama", "--version"): "ollama version is 0.32.9",
        }

    def run(self, *command: str) -> str:
        self.commands.append(command)
        return self.responses[command]


def test_system_collector_captures_every_required_reproducibility_field(monkeypatch: object) -> None:
    runner = FakeRunner()
    monkeypatch.setattr("benchmarks.hardware.os.cpu_count", lambda: 12)  # type: ignore[attr-defined]
    monkeypatch.setattr("benchmarks.hardware.platform.machine", lambda: "x86_64")  # type: ignore[attr-defined]
    monkeypatch.setattr("benchmarks.hardware.platform.python_version", lambda: "3.10.20")  # type: ignore[attr-defined]
    monkeypatch.setattr("benchmarks.hardware.version", lambda package: {"numpy": "1.26.4", "scipy": "1.12.0", "pymongo": "4.13.2"}[package])  # type: ignore[attr-defined]

    manifest = SystemHardwareManifestCollector(
        runner,
        {"OLLAMA_CHAT_MODEL": "gemma4:e4b", "OLLAMA_EMBEDDING_MODEL": "embeddinggemma"},
    ).collect()

    assert manifest == HardwareManifest(
        macos_version="15.7.7",
        cpu_model="Intel Core i7-8850H",
        architecture="x86_64",
        physical_cores=6,
        logical_cpus=12,
        ram_bytes=17179869184,
        docker_version="28.0.0",
        docker_allocated_cpus=6,
        docker_allocated_ram_bytes=8589934592,
        mongodb_version="8.0.0",
        postgresql_version="17.0",
        python_version="3.10.20",
        numpy_version="1.26.4",
        scipy_version="1.12.0",
        pymongo_version="4.13.2",
        ollama_version="ollama version is 0.32.9",
        chat_model="gemma4:e4b",
        embedding_model="embeddinggemma",
    )


def test_collector_uses_project_model_defaults(monkeypatch: object) -> None:
    runner = FakeRunner()
    monkeypatch.setattr("benchmarks.hardware.os.cpu_count", lambda: 12)  # type: ignore[attr-defined]
    monkeypatch.setattr("benchmarks.hardware.platform.machine", lambda: "x86_64")  # type: ignore[attr-defined]
    monkeypatch.setattr("benchmarks.hardware.platform.python_version", lambda: "3.10.20")  # type: ignore[attr-defined]
    monkeypatch.setattr("benchmarks.hardware.version", lambda package: "test")  # type: ignore[attr-defined]

    manifest = SystemHardwareManifestCollector(runner, {}).collect()

    assert manifest.chat_model == "gemma4:e4b"
    assert manifest.embedding_model == "embeddinggemma"
