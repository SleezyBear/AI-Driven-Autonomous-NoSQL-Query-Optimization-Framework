"""Frozen CommerceBench dataset/workload validation for authoritative runs.

Authoritative R28 runs must prove the *materialized* dataset, not merely a
profile enum.  Validation fails closed when observed collection counts, seed,
or generator version drift from the frozen values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .dataset import COMMERCEBENCH_SEED, GENERATOR_VERSION, PROFILE_RECORD_COUNTS, COLLECTIONS, DatasetSnapshot, WorkloadProfile
from .workloads import workload_fingerprint

_COUNT_NAMES = ("customers", "products", "orders", "events", "inventory")


@dataclass(frozen=True)
class DatasetValidation:
    """Persistable proof that an authoritative dataset matches the freeze."""

    profile: str
    seed: int
    generator_version: str
    expected_counts: dict[str, int]
    observed_counts: dict[str, int]
    dataset_fingerprint: str
    workload_fingerprint: str

    def to_manifest(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "seed": self.seed,
            "generator_version": self.generator_version,
            "expected_collection_counts": dict(self.expected_counts),
            "observed_collection_counts": dict(self.observed_counts),
            "dataset_fingerprint": self.dataset_fingerprint,
            "workload_fingerprint": self.workload_fingerprint,
        }


def expected_counts(profile: WorkloadProfile) -> dict[str, int]:
    """Return the frozen record counts for a profile as a named mapping."""
    return dict(zip(_COUNT_NAMES, PROFILE_RECORD_COUNTS[profile.value]))


def validate_snapshot(snapshot: DatasetSnapshot) -> DatasetValidation:
    """Validate a generated snapshot against the frozen seed/version/counts."""
    expected = expected_counts(snapshot.profile)
    observed = snapshot.collection_counts
    if snapshot.seed != COMMERCEBENCH_SEED:
        raise ValueError(f"dataset seed {snapshot.seed} does not match frozen seed {COMMERCEBENCH_SEED}")
    if snapshot.generator_version != GENERATOR_VERSION:
        raise ValueError(f"generator version {snapshot.generator_version} does not match frozen {GENERATOR_VERSION}")
    if observed != expected:
        raise ValueError(f"dataset counts {observed} do not match frozen {expected}")
    return DatasetValidation(
        profile=snapshot.profile.value,
        seed=snapshot.seed,
        generator_version=snapshot.generator_version,
        expected_counts=expected,
        observed_counts=observed,
        dataset_fingerprint=snapshot.fingerprint,
        workload_fingerprint=workload_fingerprint(),
    )


def validate_materialized(validation: DatasetValidation, observed: Mapping[str, int]) -> DatasetValidation:
    """Validate counts read back from the live target before measurement."""
    normalized = {name: int(observed.get(name, -1)) for name in COLLECTIONS}
    if normalized != validation.expected_counts:
        raise ValueError(f"materialized collection counts {normalized} do not match frozen {validation.expected_counts}")
    return validation
