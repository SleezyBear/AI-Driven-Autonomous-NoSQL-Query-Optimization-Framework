"""R28: integration proof that the delta reset restores exact equivalent state.

Runs against a real MongoDB 8 replica set when reachable, in an isolated
database, and skips otherwise.  Uses the SMOKE dataset so the proof is fast.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from pymongo import MongoClient

from benchmarks.commercebench import CommerceBench, WorkloadProfile
from benchmarks.commercebench.validation import expected_counts
from benchmarks.mongodb_executor import BenchmarkExecutionSettings, JsonTrialResultStore, RealMongoBenchmarkExecutor
from benchmarks.reset import delta_reset, observed_digest
from benchmarks.runner import BenchmarkArmOrder

URI = os.environ.get("MONGODB_EXECUTOR_URI") or "mongodb://control_plane_root:control_plane_root_dev_only@127.0.0.1:27018/?authSource=admin&directConnection=true"
DATABASE = "commercebench_reset_test"


def _connect() -> MongoClient:
    try:
        client: MongoClient = MongoClient(URI, serverSelectionTimeoutMS=1_500)
        client.admin.command("ping")
        return client
    except Exception as error:  # noqa: BLE001 - skip when no live target
        pytest.skip(f"MongoDB not reachable for reset integration proof: {error}")


@pytest.fixture()
def env(tmp_path: Path):
    client = _connect()
    snapshot = CommerceBench().reset(WorkloadProfile.SMOKE)
    executor = RealMongoBenchmarkExecutor(
        URI,
        database_name=DATABASE,
        settings=BenchmarkExecutionSettings(warmup_operations=5, measurement_operations=20),
        reset_implementation="delta",
    )
    executor.materialize_and_count(snapshot)
    yield client, snapshot, executor, tmp_path
    client.drop_database(DATABASE)
    client.close()


def test_materialization_counts_match_frozen_smoke_counts(env) -> None:
    _client, _snapshot, _executor, _tmp = env
    assert env[2]._reset_plan is not None
    database = _client[DATABASE]
    frozen = expected_counts(WorkloadProfile.SMOKE)
    observed = {name: int(database[name].count_documents({})) for name in frozen}
    assert observed == frozen


def test_pristine_state_matches_frozen_seed_and_fingerprint(env) -> None:
    client, snapshot, executor, _tmp = env
    plan = executor._reset_plan
    assert plan is not None
    assert snapshot.seed == 42
    assert plan.dataset_fingerprint == snapshot.fingerprint
    assert observed_digest(client[DATABASE], plan) == plan.expected_digest


def test_reset_restores_mutated_documents_and_removes_synthetic_events(env) -> None:
    client, snapshot, executor, tmp = env
    database = client[DATABASE]
    plan = executor._reset_plan
    assert plan is not None
    pristine = observed_digest(database, plan)
    output = tmp / "pair.jsonl"
    baseline, candidate = executor.run_pair(
        "it-delta-pair",
        snapshot,
        JsonTrialResultStore(output),
        BenchmarkArmOrder.AB,
        candidate_setup=lambda db: db.orders.create_index([("customer_id", 1)], name="optimizer_it"),
    )
    # Both arms began from the exact pristine content fingerprint.
    assert baseline.reset_fingerprint == candidate.reset_fingerprint == pristine
    # Treatment and workload mutations are present after the pair.
    assert observed_digest(database, plan) != pristine
    # Delta reset restores exactly and is idempotent.
    delta_reset(database, plan)
    assert observed_digest(database, plan) == pristine
    delta_reset(database, plan)
    assert observed_digest(database, plan) == pristine
    # No optimizer-owned index remains.
    assert all(not name.startswith("optimizer_") for name in database["orders"].index_information())
    assert int(database["events"].count_documents({"_id": {"$gte": 10_000_000}})) == 0


def test_b0_native_arm_applies_no_candidate_treatment(env) -> None:
    client, snapshot, executor, tmp = env
    database = client[DATABASE]
    plan = executor._reset_plan
    assert plan is not None
    baseline, candidate = executor.run_pair(
        "it-b0-pair", snapshot, JsonTrialResultStore(tmp / "b0.jsonl"), BenchmarkArmOrder.AB, candidate_setup=None
    )
    assert baseline.reset_fingerprint == candidate.reset_fingerprint == plan.expected_digest
    assert all(not name.startswith("optimizer_") for name in database["orders"].index_information())


def test_equivalent_reset_survives_ba_arm_order(env) -> None:
    client, snapshot, executor, tmp = env
    database = client[DATABASE]
    plan = executor._reset_plan
    assert plan is not None
    baseline, candidate = executor.run_pair(
        "it-ba-pair",
        snapshot,
        JsonTrialResultStore(tmp / "ba.jsonl"),
        BenchmarkArmOrder.BA,
        candidate_setup=lambda db: db.inventory.create_index([("product_id", 1)], name="optimizer_it_inv"),
    )
    assert baseline.reset_fingerprint == candidate.reset_fingerprint == plan.expected_digest
    delta_reset(database, plan)
    assert observed_digest(database, plan) == plan.expected_digest


def test_reset_failure_fails_closed_when_state_cannot_be_restored(env) -> None:
    client, snapshot, executor, _tmp = env
    database = client[DATABASE]
    plan = executor._reset_plan
    assert plan is not None
    missing_id = plan.inventory_available[0][0]
    database["inventory"].delete_one({"_id": missing_id})
    with pytest.raises(RuntimeError, match="exact equivalent starting state"):
        delta_reset(database, plan)
    executor.materialize_and_count(snapshot)
