"""Phase 16 JSON safety-policy tests."""

import pytest

from app.admission.policy import DEFAULT_POLICIES, ZERO_TOLERANCE_INVARIANTS, load_default_policy
from app.admission.statistics import calculate_allowed_regression


def test_json_policy_exposes_frozen_metric_limits_and_separate_invariants() -> None:
    assert DEFAULT_POLICIES["p95_latency_ms"].relative_cap == 0.03
    assert DEFAULT_POLICIES["p95_latency_ms"].absolute_cap == 50
    assert DEFAULT_POLICIES["cpu_utilization"].hard_upper_boundary == 0.80
    assert DEFAULT_POLICIES["cpu_utilization"].headroom_fraction == 0.10
    assert "result_correctness" in ZERO_TOLERANCE_INVARIANTS


def test_dynamic_margin_uses_json_relative_absolute_and_headroom_limits() -> None:
    policy = DEFAULT_POLICIES["cpu_utilization"]
    assert calculate_allowed_regression(0.61, policy) == pytest.approx(0.019)


def test_policy_loader_is_deterministic() -> None:
    policies, invariants = load_default_policy()
    assert policies == DEFAULT_POLICIES
    assert invariants == ZERO_TOLERANCE_INVARIANTS
