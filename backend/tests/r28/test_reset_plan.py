"""R28: pure reset-plan tests for the frozen workload mutation set."""
from __future__ import annotations

from benchmarks.commercebench import CommerceBench, WorkloadProfile
from benchmarks.reset import (
    EVENT_INSERT_BASE,
    MUTATED_INVENTORY_PRODUCT_IDS,
    MUTATED_ORDER_IDS,
    OPTIMIZER_INDEX_PREFIX,
    build_reset_plan,
)


def _smoke_snapshot():
    return CommerceBench().reset(WorkloadProfile.SMOKE)


def test_mutation_set_covers_only_the_frozen_workload_writes() -> None:
    assert MUTATED_ORDER_IDS[0] == 1 and MUTATED_ORDER_IDS[-1] == 10_000
    assert MUTATED_INVENTORY_PRODUCT_IDS[0] == 1 and MUTATED_INVENTORY_PRODUCT_IDS[-1] == 500
    assert EVENT_INSERT_BASE == 10_000_000
    assert OPTIMIZER_INDEX_PREFIX == "optimizer_"


def test_plan_records_exact_pristine_mutated_values() -> None:
    snapshot = _smoke_snapshot()
    plan = build_reset_plan(snapshot)
    assert len(plan.orders_status) == 10_000
    assert plan.orders_status[0] == (1, snapshot.documents_for("orders")[0]["status"])
    assert plan.dataset_fingerprint == snapshot.fingerprint
    inventory = snapshot.documents_for("inventory")
    assert len(plan.inventory_available) == len(inventory)
    assert all(document["product_id"] in set(MUTATED_INVENTORY_PRODUCT_IDS) for document in inventory)


def test_expected_digest_is_deterministic_and_content_addressed() -> None:
    plan_a = build_reset_plan(_smoke_snapshot())
    plan_b = build_reset_plan(_smoke_snapshot())
    assert plan_a.expected_digest == plan_b.expected_digest
    assert len(plan_a.expected_digest) == 64
    assert dict(plan_a.counts) == _smoke_snapshot().collection_counts
