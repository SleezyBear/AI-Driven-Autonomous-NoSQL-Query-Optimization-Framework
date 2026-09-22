"""R28: authoritative dataset materialization and frozen fingerprint validation."""

from __future__ import annotations

import pytest

from benchmarks.commercebench import COMMERCEBENCH_SEED, GENERATOR_VERSION, CommerceBench, WorkloadProfile
from benchmarks.commercebench.validation import expected_counts, validate_materialized, validate_snapshot


def test_frozen_counts_match_the_documented_volumes() -> None:
    assert expected_counts(WorkloadProfile.SMOKE) == {
        "customers": 1_000,
        "products": 500,
        "orders": 10_000,
        "events": 20_000,
        "inventory": 3_000,
    }
    assert expected_counts(WorkloadProfile.STANDARD) == {
        "customers": 20_000,
        "products": 10_000,
        "orders": 200_000,
        "events": 500_000,
        "inventory": 30_000,
    }
    assert expected_counts(WorkloadProfile.PUBLICATION) == {
        "customers": 100_000,
        "products": 50_000,
        "orders": 1_000_000,
        "events": 2_000_000,
        "inventory": 150_000,
    }


def test_snapshot_validation_records_seed_version_and_fingerprints() -> None:
    validation = validate_snapshot(CommerceBench().reset(WorkloadProfile.SMOKE))
    manifest = validation.to_manifest()
    assert manifest["seed"] == COMMERCEBENCH_SEED == 42
    assert manifest["generator_version"] == GENERATOR_VERSION
    assert manifest["observed_collection_counts"] == manifest["expected_collection_counts"]
    assert manifest["dataset_fingerprint"]
    assert manifest["workload_fingerprint"]


def test_materialized_counts_must_match_frozen_expectations() -> None:
    validation = validate_snapshot(CommerceBench().reset(WorkloadProfile.SMOKE))
    observed = dict(validation.expected_counts)
    assert validate_materialized(validation, observed) is validation
    drifted = dict(observed)
    drifted["orders"] = drifted["orders"] - 1
    with pytest.raises(ValueError, match="materialized collection counts"):
        validate_materialized(validation, drifted)
