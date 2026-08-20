"""A/A sample sizing and dynamic-margin tests."""

import pytest

from app.admission.policy import DEFAULT_POLICIES
from app.admission.statistics import calculate_allowed_regression, estimate_required_pairs


def test_cpu_headroom_restricts_dynamic_margin() -> None:
    assert calculate_allowed_regression(0.79, DEFAULT_POLICIES["cpu_utilization"]) == pytest.approx(0.001)


def test_baseline_over_boundary_has_zero_margin_without_division_error() -> None:
    assert calculate_allowed_regression(0.82, DEFAULT_POLICIES["cpu_utilization"]) == 0
    assert estimate_required_pairs((0.01, -0.01), 0, 30) == 30


def test_noise_requires_more_than_profile_maximum() -> None:
    assert estimate_required_pairs((-1, 1, -1, 1), 0.01, 30) > 30
