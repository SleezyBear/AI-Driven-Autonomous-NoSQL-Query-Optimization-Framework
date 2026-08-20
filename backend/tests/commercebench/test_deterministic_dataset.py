"""Phase 13 acceptance tests for CommerceBench."""

from benchmarks.commercebench import COMMERCEBENCH_SEED, CommerceBench, WorkloadProfile
from benchmarks.commercebench.dataset import COLLECTIONS


def test_two_resets_produce_identical_dataset_fingerprints() -> None:
    benchmark = CommerceBench()

    first = benchmark.reset(WorkloadProfile.SMOKE)
    second = benchmark.reset(WorkloadProfile.SMOKE)

    assert first.seed == COMMERCEBENCH_SEED == 42
    assert first.fingerprint == second.fingerprint
    assert first.collections == second.collections
    assert tuple(name for name, _ in first.collections) == COLLECTIONS


def test_all_declared_profiles_generate_the_required_collections() -> None:
    benchmark = CommerceBench()

    snapshots = [benchmark.reset(profile) for profile in WorkloadProfile]

    assert [snapshot.profile for snapshot in snapshots] == list(WorkloadProfile)
    assert all(snapshot.documents_for("customers") for snapshot in snapshots)
    assert all(snapshot.documents_for("products") for snapshot in snapshots)
    assert all(snapshot.documents_for("orders") for snapshot in snapshots)
    assert all(snapshot.documents_for("events") for snapshot in snapshots)
    assert all(snapshot.documents_for("inventory") for snapshot in snapshots)
