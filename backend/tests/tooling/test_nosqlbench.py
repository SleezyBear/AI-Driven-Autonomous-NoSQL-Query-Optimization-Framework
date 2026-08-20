"""Phase 41 static checks for isolated NoSQLBench smoke-workload configuration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_nosqlbench_smoke_is_a_pinned_linux_amd64_container_workload() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()
    workload = (ROOT / "benchmarks/nosqlbench/smoke.yaml").read_text()
    makefile = (ROOT / "Makefile").read_text()

    assert "nosqlbench/nosqlbench:5.25.13" in compose
    assert "platform: linux/amd64" in compose
    assert "driver=stdout" in compose
    assert "cycles=3" in compose
    assert "nosqlbench-smoke-cycle" in workload
    assert "docker compose --profile bench run --rm nosqlbench-smoke" in makefile
    assert "nosqlbench" not in (ROOT / "requirements.txt").read_text().lower()
