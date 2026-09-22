"""Frozen PUBLICATION sampling protocol and required-pair calculation.

The PUBLICATION profile is defined once, in ``app.admission.policy``:
60-second warmup, 120-second measurement, 12 A/A calibration pairs, 15-40
candidate pairs, and 10,000 bootstrap resamples.  This module exposes that
protocol and reuses the accepted ``app.admission.statistics`` implementation
for required-N calculation; it never reinterprets seconds as operation counts
and never weakens a bound.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from app.admission.models import BenchmarkProfile, MetricDirection, MetricPolicy, ProfileSettings
from app.admission.policy import PROFILES
from app.admission.statistics import (
    calculate_allowed_regression,
    calculate_baseline_reference,
    calculate_transformed_minimum_benefit,
    calculate_transformed_regression_margin,
    estimate_required_pairs,
)

MINIMUM_OBSERVATIONS = 3


class SamplingStatus(str, Enum):
    """Outcome of the A/A calibration / required-N decision."""

    SAMPLING_COMPLETE = "SAMPLING_COMPLETE"
    INCONCLUSIVE_NOISE = "INCONCLUSIVE_NOISE"


class ProtocolDriftError(RuntimeError):
    """Raised when the frozen PUBLICATION protocol has been altered."""


@dataclass(frozen=True)
class PublicationProtocol:
    """The frozen, non-negotiable PUBLICATION execution protocol."""

    profile: BenchmarkProfile
    warmup_seconds: int
    measurement_seconds: int
    aa_pairs: int
    minimum_candidate_pairs: int
    maximum_candidate_pairs: int
    bootstrap_samples: int
    confidence: float
    production_eligible: bool

    def __post_init__(self) -> None:
        self.assert_frozen()

    def assert_frozen(self) -> None:
        """Fail closed if any frozen value has been reinterpreted or weakened."""
        if self.profile is not BenchmarkProfile.PUBLICATION:
            raise ProtocolDriftError("publication protocol must target the PUBLICATION profile")
        expected = {
            "warmup_seconds": 60,
            "measurement_seconds": 120,
            "aa_pairs": 12,
            "minimum_candidate_pairs": 15,
            "maximum_candidate_pairs": 40,
            "bootstrap_samples": 10_000,
        }
        actual = {
            "warmup_seconds": self.warmup_seconds,
            "measurement_seconds": self.measurement_seconds,
            "aa_pairs": self.aa_pairs,
            "minimum_candidate_pairs": self.minimum_candidate_pairs,
            "maximum_candidate_pairs": self.maximum_candidate_pairs,
            "bootstrap_samples": self.bootstrap_samples,
        }
        drift = {name: (expected[name], actual[name]) for name in expected if expected[name] != actual[name]}
        if drift:
            raise ProtocolDriftError(f"frozen PUBLICATION protocol drifted: {drift}")
        if self.production_eligible:
            raise ProtocolDriftError("PUBLICATION is not a production-deployment profile")


def publication_protocol(settings: ProfileSettings | None = None) -> PublicationProtocol:
    """Return the frozen PUBLICATION protocol, derived from accepted policy."""
    resolved = settings or PROFILES[BenchmarkProfile.PUBLICATION]
    if resolved.pilot_aa_pairs is None or resolved.minimum_candidate_pairs is None or resolved.maximum_candidate_pairs is None:
        raise ProtocolDriftError("PUBLICATION profile is missing calibration pair bounds")
    protocol = PublicationProtocol(
        profile=BenchmarkProfile.PUBLICATION,
        warmup_seconds=resolved.warmup_seconds,
        measurement_seconds=resolved.measurement_seconds,
        aa_pairs=resolved.pilot_aa_pairs,
        minimum_candidate_pairs=resolved.minimum_candidate_pairs,
        maximum_candidate_pairs=resolved.maximum_candidate_pairs,
        bootstrap_samples=resolved.bootstrap_samples,
        confidence=resolved.confidence,
        production_eligible=resolved.production_eligible,
    )
    protocol.assert_frozen()
    return protocol


@dataclass(frozen=True)
class RequiredPairs:
    """The accepted required-N result and its frozen-range disposition."""

    required_pairs: int
    minimum_pairs: int
    maximum_pairs: int
    status: SamplingStatus


def required_candidate_pairs(
    *,
    aa_scores: Iterable[float],
    baseline_values: Iterable[float],
    policy: MetricPolicy,
    primary_direction: MetricDirection,
    minimum_benefit: float,
    minimum_pairs: int,
    maximum_pairs: int,
) -> RequiredPairs:
    """Compute required candidate pairs using the accepted A/A formula.

    Mirrors ``evaluate_candidate_admission``: required count is the maximum
    over the protected metric, the primary benefit gate, the minimum
    observations floor, and the profile minimum.  A value above the profile
    maximum is ``INCONCLUSIVE_NOISE`` and is never clamped down.
    """
    scores = tuple(float(score) for score in aa_scores)
    baselines = tuple(float(value) for value in baseline_values)
    reference = calculate_baseline_reference(baselines, policy.comparison_mode)
    margin = calculate_transformed_regression_margin(reference, calculate_allowed_regression(reference, policy), policy)
    protected_required = estimate_required_pairs(scores, margin, maximum_pairs)
    primary_required = estimate_required_pairs(
        scores, calculate_transformed_minimum_benefit(primary_direction, minimum_benefit), maximum_pairs
    )
    required = max(MINIMUM_OBSERVATIONS, minimum_pairs, protected_required, primary_required)
    status = SamplingStatus.INCONCLUSIVE_NOISE if required > maximum_pairs else SamplingStatus.SAMPLING_COMPLETE
    return RequiredPairs(
        required_pairs=required,
        minimum_pairs=minimum_pairs,
        maximum_pairs=maximum_pairs,
        status=status,
    )
