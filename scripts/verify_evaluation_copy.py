"""Seed monitored MongoDB and verify an isolated physical evaluation clone."""

from __future__ import annotations

import sys
from uuid import uuid4
from pathlib import Path

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from app.evaluation.mongodb_copier import MongoEvaluationStateCopier  # noqa: E402
from benchmarks.commercebench import CommerceBench, WorkloadProfile, mixed_workload_shapes  # noqa: E402


MONITORED_URI = "mongodb://control_plane_root:control_plane_root_dev_only@localhost:27017/?authSource=admin&directConnection=true"
EVALUATION_URI = "mongodb://control_plane_root:control_plane_root_dev_only@localhost:27018/?authSource=admin&directConnection=true"


async def main() -> int:
    snapshot = CommerceBench().reset(WorkloadProfile.SMOKE)
    database_name = f"commercebench_r15_{uuid4().hex}"
    with MongoClient(MONITORED_URI, serverSelectionTimeoutMS=5_000) as client:
        database = client[database_name]
        for name, documents in snapshot.collections:
            database[name].insert_many(list(documents), ordered=True)
        database.orders.create_index([("customer_id", 1)], name="source_customer_id")
    copier = MongoEvaluationStateCopier(MONITORED_URI, EVALUATION_URI, database_name, mixed_workload_shapes())
    state = await copier.copy_and_verify("mongo-monitored", "mongo-evaluation")
    assert state.source_dataset_fingerprint == state.evaluation_dataset_fingerprint
    assert state.source_topology_identity != state.evaluation_topology_identity
    print(f"dataset_fingerprint={state.source_dataset_fingerprint}")
    print(f"mongodb_version={state.mongodb_version}")
    print(f"fcv={state.feature_compatibility_version}")
    print(f"workload_fingerprint={state.workload_fingerprint}")
    print("evaluation clone verification: PASS")
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
