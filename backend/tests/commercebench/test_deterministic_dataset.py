"""Phase 13 acceptance tests for CommerceBench."""

from benchmarks.commercebench import COMMERCEBENCH_SEED, GENERATOR_VERSION, PROFILE_RECORD_COUNTS, CommerceBench, WorkloadKind, WorkloadProfile, mixed_workload_shapes
from benchmarks.commercebench.dataset import COLLECTIONS


def test_two_resets_produce_identical_dataset_fingerprints() -> None:
    benchmark = CommerceBench()

    first = benchmark.reset(WorkloadProfile.SMOKE)
    second = benchmark.reset(WorkloadProfile.SMOKE)

    assert first.seed == COMMERCEBENCH_SEED == 42
    assert first.generator_version == GENERATOR_VERSION
    assert first.fingerprint == second.fingerprint
    assert first.collections == second.collections
    assert tuple(name for name, _ in first.collections) == COLLECTIONS
    assert first.collection_counts == {
        "customers": 1_000,
        "products": 500,
        "orders": 10_000,
        "events": 20_000,
        "inventory": 3_000,
    }


def test_all_declared_profiles_have_the_exact_defined_record_counts() -> None:
    assert PROFILE_RECORD_COUNTS == {
        WorkloadProfile.SMOKE.value: (1_000, 500, 10_000, 20_000, 3_000),
        WorkloadProfile.STANDARD.value: (20_000, 10_000, 200_000, 500_000, 30_000),
        WorkloadProfile.PUBLICATION.value: (100_000, 50_000, 1_000_000, 2_000_000, 150_000),
    }


def test_workload_definition_is_a_mixed_read_write_traffic_profile() -> None:
    workloads = mixed_workload_shapes()

    assert sum(shape.weight for shape in workloads) == 100
    assert {shape.kind for shape in workloads} == {WorkloadKind.READ, WorkloadKind.WRITE}
    assert {shape.collection for shape in workloads} == set(COLLECTIONS)
