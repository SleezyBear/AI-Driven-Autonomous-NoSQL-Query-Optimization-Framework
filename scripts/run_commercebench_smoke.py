"""Run a real controlled CommerceBench SMOKE pair against Docker MongoDB."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from benchmarks.commercebench import CommerceBench, WorkloadProfile  # noqa: E402
from benchmarks.mongodb_executor import (  # noqa: E402
    BenchmarkExecutionSettings,
    JsonTrialResultStore,
    RealMongoBenchmarkExecutor,
)
from benchmarks.runner import BenchmarkArmOrder  # noqa: E402


DEFAULT_URI = "mongodb://control_plane_root:control_plane_root_dev_only@localhost:27018/?authSource=admin&directConnection=true"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=DEFAULT_URI)
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks/results/commercebench-smoke-trials.json")
    arguments = parser.parse_args()
    executor = RealMongoBenchmarkExecutor(arguments.uri, settings=BenchmarkExecutionSettings(warmup_operations=10, measurement_operations=50))
    baseline, candidate = executor.run_pair(
        "commercebench-smoke-001",
        CommerceBench().reset(WorkloadProfile.SMOKE),
        JsonTrialResultStore(arguments.output),
        BenchmarkArmOrder.AB,
        candidate_setup=lambda database: database.orders.create_index([("customer_id", 1)], name="candidate_customer_id"),
    )
    if not baseline.measurement.successful_operations or not candidate.measurement.successful_operations:
        raise RuntimeError("both real benchmark arms must record successful operations")
    print(f"baseline_successful_operations={baseline.measurement.successful_operations}")
    print(f"candidate_successful_operations={candidate.measurement.successful_operations}")
    print(f"baseline_throughput={baseline.measurement.throughput_successful_ops_per_second:.3f}")
    print(f"candidate_throughput={candidate.measurement.throughput_successful_ops_per_second:.3f}")
    print(f"evidence={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
