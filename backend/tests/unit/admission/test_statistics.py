"""Transforms and deterministic bootstrap tests."""

import pytest

from app.admission.models import ComparisonMode, MetricDirection
from app.admission.statistics import paired_bootstrap_ci, transform_regression


@pytest.mark.parametrize("direction", [MetricDirection.LOWER_IS_BETTER, MetricDirection.HIGHER_IS_BETTER])
def test_regression_sign_convention(direction: MetricDirection) -> None:
    worse = (100, 110) if direction == MetricDirection.LOWER_IS_BETTER else (100, 90)
    better = (100, 90) if direction == MetricDirection.LOWER_IS_BETTER else (100, 110)
    assert transform_regression(*worse, direction, ComparisonMode.LOG_RATIO) > 0
    assert transform_regression(100, 100, direction, ComparisonMode.LOG_RATIO) == pytest.approx(0)
    assert transform_regression(*better, direction, ComparisonMode.LOG_RATIO) < 0


def test_zero_log_ratio_cases_are_explicit() -> None:
    assert transform_regression(0, 0, MetricDirection.LOWER_IS_BETTER, ComparisonMode.LOG_RATIO) == 0
    assert transform_regression(0, 1, MetricDirection.LOWER_IS_BETTER, ComparisonMode.LOG_RATIO) > 0


def test_bootstrap_is_reproducible() -> None:
    scores = (-0.2, -0.21, -0.19)
    assert paired_bootstrap_ci(scores, 1000, 42) == paired_bootstrap_ci(scores, 1000, 42)
