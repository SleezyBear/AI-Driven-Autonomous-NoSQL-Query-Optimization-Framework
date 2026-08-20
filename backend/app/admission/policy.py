"""Frozen Phase-15 profile and protected-metric policy values."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.admission.models import BenchmarkProfile, ComparisonMode, MetricDirection, MetricPolicy, ProfileSettings

PROFILES = {
    BenchmarkProfile.SMOKE: ProfileSettings(False, 5, 10, 1000, 0.95, candidate_pairs=3),
    BenchmarkProfile.AUTONOMOUS: ProfileSettings(True, 30, 60, 10000, 0.95, pilot_aa_pairs=10, minimum_candidate_pairs=10, maximum_candidate_pairs=30),
    BenchmarkProfile.PUBLICATION: ProfileSettings(False, 60, 120, 10000, 0.95, pilot_aa_pairs=12, minimum_candidate_pairs=15, maximum_candidate_pairs=40),
}

POLICY_PATH = Path(__file__).with_name("default_policy.json")


def load_default_policy(path: Path = POLICY_PATH) -> tuple[dict[str, MetricPolicy], tuple[str, ...]]:
    """Load the frozen JSON policy and reject malformed or incomplete policy entries."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError("Unsupported safety-policy document.")
    minimum_benefit = document.get("minimum_meaningful_improvement")
    metrics = document.get("metrics")
    invariants = document.get("zero_tolerance_invariants")
    if not isinstance(minimum_benefit, (int, float)) or not isinstance(metrics, dict) or not isinstance(invariants, list):
        raise ValueError("Safety-policy document is malformed.")
    policies: dict[str, MetricPolicy] = {}
    for key, raw_value in metrics.items():
        if not isinstance(key, str) or not isinstance(raw_value, dict):
            raise ValueError("Safety-policy metric entry is malformed.")
        policies[key] = MetricPolicy(
            metric_key=key,
            direction=MetricDirection(raw_value["direction"]),
            comparison_mode=ComparisonMode(raw_value["comparison_mode"]),
            relative_cap=_optional_number(raw_value.get("relative_cap")),
            absolute_cap=_optional_number(raw_value.get("absolute_cap")),
            hard_upper_boundary=_optional_number(raw_value.get("hard_upper_boundary")),
            headroom_fraction=_optional_number(raw_value.get("headroom_fraction")),
            minimum_benefit=float(minimum_benefit),
        )
    return policies, tuple(str(invariant) for invariant in invariants)


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        raise ValueError("Safety-policy numerical values must be numbers.")
    return float(value)


DEFAULT_POLICIES, ZERO_TOLERANCE_INVARIANTS = load_default_policy()
