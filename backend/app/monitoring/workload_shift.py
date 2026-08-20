"""Detect sustained workload-distribution shifts without mutating production."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.workloads.snapshots import Share

TOTAL_VARIATION_THRESHOLD = 0.20
CONSECUTIVE_WINDOWS_REQUIRED = 3


@dataclass(frozen=True)
class WorkloadShiftDecision:
    """Auditable total-variation evidence for one monitoring window."""

    total_variation_distance: float
    consecutive_shift_windows: int
    shift_detected: bool
    reanalysis_requested: bool


class ReanalysisScheduler(Protocol):
    """The only post-shift capability: request analysis, never deployment."""

    async def request_reanalysis(self) -> None:
        """Request a fresh analysis from new workload evidence."""


class WorkloadShiftDetector:
    """Require three consecutive TVD threshold breaches before re-analysis."""

    def __init__(self, reanalysis_scheduler: ReanalysisScheduler) -> None:
        self._reanalysis_scheduler = reanalysis_scheduler
        self._consecutive_shift_windows = 0
        self._shift_episode_open = False

    async def observe(
        self, baseline_distribution: tuple[Share, ...], observed_distribution: tuple[Share, ...]
    ) -> WorkloadShiftDecision:
        """Evaluate one window and request re-analysis once for a sustained shift episode."""
        distance = total_variation_distance(baseline_distribution, observed_distribution)
        if distance + 1e-12 >= TOTAL_VARIATION_THRESHOLD:
            self._consecutive_shift_windows += 1
        else:
            self._consecutive_shift_windows = 0
            self._shift_episode_open = False

        detected = self._consecutive_shift_windows >= CONSECUTIVE_WINDOWS_REQUIRED
        requested = detected and not self._shift_episode_open
        if requested:
            await self._reanalysis_scheduler.request_reanalysis()
            self._shift_episode_open = True
        return WorkloadShiftDecision(distance, self._consecutive_shift_windows, detected, requested)


def total_variation_distance(
    baseline_distribution: tuple[Share, ...], observed_distribution: tuple[Share, ...]
) -> float:
    """Return TVD over the union of literal-free workload-shape identifiers."""
    baseline = _validated_distribution(baseline_distribution)
    observed = _validated_distribution(observed_distribution)
    return 0.5 * sum(abs(baseline.get(name, 0.0) - observed.get(name, 0.0)) for name in baseline.keys() | observed.keys())


def _validated_distribution(distribution: tuple[Share, ...]) -> dict[str, float]:
    values: dict[str, float] = {}
    for share in distribution:
        if not share.name or share.name in values or not 0.0 <= share.fraction <= 1.0:
            raise ValueError("workload distribution must contain unique probability shares")
        values[share.name] = share.fraction
    if values and abs(sum(values.values()) - 1.0) > 1e-9:
        raise ValueError("workload distribution fractions must sum to one")
    return values
