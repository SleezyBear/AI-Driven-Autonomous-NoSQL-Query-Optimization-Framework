"""Phase 36 acceptance tests for sustained total-variation shift detection."""

import pytest

from app.monitoring.workload_shift import (
    CONSECUTIVE_WINDOWS_REQUIRED,
    TOTAL_VARIATION_THRESHOLD,
    WorkloadShiftDetector,
    total_variation_distance,
)
from app.workloads.snapshots import Share


class SpyReanalysisScheduler:
    def __init__(self) -> None:
        self.request_count = 0

    async def request_reanalysis(self) -> None:
        self.request_count += 1


def test_total_variation_distance_uses_the_union_of_shapes() -> None:
    baseline = (Share("a", 0.8), Share("b", 0.2))
    observed = (Share("a", 0.6), Share("c", 0.4))

    assert total_variation_distance(baseline, observed) == pytest.approx(0.4)


@pytest.mark.asyncio
async def test_requires_three_consecutive_windows_at_the_fixed_threshold() -> None:
    scheduler = SpyReanalysisScheduler()
    detector = WorkloadShiftDetector(scheduler)
    baseline = (Share("a", 1.0),)
    observed = (Share("a", 1.0 - TOTAL_VARIATION_THRESHOLD), Share("b", TOTAL_VARIATION_THRESHOLD))

    first = await detector.observe(baseline, observed)
    second = await detector.observe(baseline, observed)
    third = await detector.observe(baseline, observed)

    assert first.shift_detected is False
    assert second.shift_detected is False
    assert third.consecutive_shift_windows == CONSECUTIVE_WINDOWS_REQUIRED
    assert third.shift_detected is True
    assert third.reanalysis_requested is True
    assert scheduler.request_count == 1


@pytest.mark.asyncio
async def test_a_non_shift_window_resets_the_sequence_and_no_production_action_exists() -> None:
    scheduler = SpyReanalysisScheduler()
    detector = WorkloadShiftDetector(scheduler)
    baseline = (Share("a", 1.0),)
    shifted = (Share("a", 0.7), Share("b", 0.3))

    await detector.observe(baseline, shifted)
    await detector.observe(baseline, baseline)
    result = await detector.observe(baseline, shifted)

    assert result.consecutive_shift_windows == 1
    assert result.shift_detected is False
    assert result.reanalysis_requested is False
    assert scheduler.request_count == 0
