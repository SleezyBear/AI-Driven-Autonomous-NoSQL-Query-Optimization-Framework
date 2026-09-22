"""R28: PUBLICATION windows are seconds and sampling respects the frozen range."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.admission.models import BenchmarkProfile, MetricDirection
from app.admission.policy import DEFAULT_POLICIES
from benchmarks.commercebench import WorkloadProfile
from benchmarks.publication import (
    ProtocolDriftError,
    PublicationProtocol,
    RequiredPairs,
    SamplingStatus,
    publication_protocol,
    required_candidate_pairs,
)
from benchmarks.r28_runner import aa_pair_ids, build_settings, candidate_pair_ids


def test_publication_profile_values_are_the_frozen_seconds_and_counts() -> None:
    protocol = publication_protocol()
    assert protocol.warmup_seconds == 60
    assert protocol.measurement_seconds == 120
    assert protocol.aa_pairs == 12
    assert protocol.minimum_candidate_pairs == 15
    assert protocol.maximum_candidate_pairs == 40
    assert protocol.bootstrap_samples == 10_000
    assert protocol.production_eligible is False
    protocol.assert_frozen()


def test_publication_settings_are_duration_based_not_operation_counts() -> None:
    settings = build_settings(WorkloadProfile.PUBLICATION)
    assert settings.duration_based is True
    assert settings.warmup_seconds == 60.0
    assert settings.measurement_seconds == 120.0
    assert settings.warmup_operations is None
    assert settings.measurement_operations is None


def test_publication_rejects_operation_count_reinterpretation() -> None:
    with pytest.raises(ValueError, match="time-based"):
        build_settings(WorkloadProfile.PUBLICATION, warmup_operations=60, measurement_operations=120)
    with pytest.raises(ValueError, match="frozen"):
        build_settings(WorkloadProfile.PUBLICATION, measurement_seconds=1.0)


def test_protocol_drift_is_rejected() -> None:
    protocol = publication_protocol()
    with pytest.raises(ProtocolDriftError):
        replace(protocol, aa_pairs=10).assert_frozen()
    with pytest.raises(ProtocolDriftError):
        replace(protocol, measurement_seconds=120_000).assert_frozen()
    with pytest.raises(ProtocolDriftError):
        replace(protocol, production_eligible=True).assert_frozen()


def test_publication_schedules_exactly_twelve_aa_calibration_pairs() -> None:
    ids = aa_pair_ids("commercebench-r28a-publication-b4_llm_with_gate")
    assert len(ids) == 12
    assert len(set(ids)) == 12


def test_candidate_sampling_is_confined_to_the_frozen_range() -> None:
    assert len(candidate_pair_ids("prefix", 15)) == 15
    assert len(candidate_pair_ids("prefix", 40)) == 40
    with pytest.raises(ValueError, match="outside the frozen"):
        candidate_pair_ids("prefix", 14)
    with pytest.raises(ValueError, match="outside the frozen"):
        candidate_pair_ids("prefix", 41)


def _required(aa_scores: tuple[float, ...]) -> RequiredPairs:
    return required_candidate_pairs(
        aa_scores=aa_scores,
        baseline_values=(100.0, 101.0, 99.0),
        policy=DEFAULT_POLICIES["p99_latency_ms"],
        primary_direction=MetricDirection.LOWER_IS_BETTER,
        minimum_benefit=0.05,
        minimum_pairs=15,
        maximum_pairs=40,
    )


def test_low_noise_requires_the_profile_minimum() -> None:
    result = _required((0.0, 0.0, 0.0, 0.0))
    assert result.required_pairs == 15
    assert result.status is SamplingStatus.SAMPLING_COMPLETE


def test_high_noise_exceeding_the_maximum_is_inconclusive() -> None:
    result = _required((0.0, 5.0, -5.0, 5.0))
    assert result.required_pairs > 40
    assert result.status is SamplingStatus.INCONCLUSIVE_NOISE


def test_drifted_protocol_construction_is_rejected() -> None:
    with pytest.raises(ProtocolDriftError):
        PublicationProtocol(
            profile=BenchmarkProfile.PUBLICATION,
            warmup_seconds=60,
            measurement_seconds=120,
            aa_pairs=10,
            minimum_candidate_pairs=15,
            maximum_candidate_pairs=40,
            bootstrap_samples=10_000,
            confidence=0.95,
            production_eligible=False,
        )
