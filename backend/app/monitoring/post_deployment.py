"""Monitor post-deployment evidence without falsely attributing workload shifts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from app.metrics.collector import MetricSnapshot
from app.rollback.owned_index import RollbackRequest, RollbackResult, RollbackStatus
from app.monitoring.workload_shift import WorkloadShiftDecision, WorkloadShiftDetector
from app.workloads.snapshots import Share


@dataclass(frozen=True)
class MonitoringWindow:
    """Literal-free post-deployment metrics and workload distribution evidence."""

    metrics: MetricSnapshot
    workload_distribution: tuple[Share, ...]


class MonitoringStatus(str, Enum):
    """The operational outcome after one post-deployment monitoring window."""

    STABLE = "STABLE"
    WORKLOAD_SHIFT_DETECTED = "WORKLOAD_SHIFT_DETECTED"
    ROLLED_BACK = "ROLLED_BACK"
    ROLLBACK_BLOCKED = "ROLLBACK_BLOCKED"


@dataclass(frozen=True)
class MonitoringResult:
    """Auditable monitoring outcome containing every observed metric group."""

    status: MonitoringStatus
    baseline: MonitoringWindow
    observed: MonitoringWindow
    catastrophic_regression: bool
    workload_shift_detected: bool
    attribution: str
    rollback_result: RollbackResult | None = None


class RollbackCoordinator(Protocol):
    """The only rollback capability available to the monitoring layer."""

    async def rollback(self, request: RollbackRequest) -> RollbackResult:
        """Attempt an ownership-verified rollback."""


class PostDeploymentMonitor:
    """Coordinate evidence, workload-shift attribution, and catastrophic rollback."""

    def __init__(self, rollback_coordinator: RollbackCoordinator) -> None:
        self._rollback_coordinator = rollback_coordinator

    async def assess(
        self,
        baseline: MonitoringWindow,
        observed: MonitoringWindow,
        catastrophic_regression: bool,
        workload_shift_detected: bool,
        rollback_request: RollbackRequest | None,
    ) -> MonitoringResult:
        """Rollback catastrophic optimizer-owned actions while retaining attribution truth."""
        attribution = "WORKLOAD_SHIFT" if workload_shift_detected else "STABLE_WORKLOAD"
        if not catastrophic_regression:
            status = MonitoringStatus.WORKLOAD_SHIFT_DETECTED if workload_shift_detected else MonitoringStatus.STABLE
            return MonitoringResult(status, baseline, observed, False, workload_shift_detected, attribution)

        if rollback_request is None:
            return MonitoringResult(
                MonitoringStatus.ROLLBACK_BLOCKED,
                baseline,
                observed,
                True,
                workload_shift_detected,
                attribution,
            )
        rollback_result = await self._rollback_coordinator.rollback(rollback_request)
        status = MonitoringStatus.ROLLED_BACK if rollback_result.status is RollbackStatus.ROLLED_BACK else MonitoringStatus.ROLLBACK_BLOCKED
        return MonitoringResult(status, baseline, observed, True, workload_shift_detected, attribution, rollback_result)

    async def assess_with_shift_detection(
        self,
        baseline: MonitoringWindow,
        observed: MonitoringWindow,
        catastrophic_regression: bool,
        rollback_request: RollbackRequest | None,
        shift_detector: WorkloadShiftDetector,
    ) -> tuple[MonitoringResult, WorkloadShiftDecision]:
        """Use sustained TVD evidence before withholding statistical attribution."""
        shift = await shift_detector.observe(baseline.workload_distribution, observed.workload_distribution)
        result = await self.assess(
            baseline, observed, catastrophic_regression, shift.shift_detected, rollback_request
        )
        return result, shift
