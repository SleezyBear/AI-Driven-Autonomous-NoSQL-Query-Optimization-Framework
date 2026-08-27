"""Monitor post-deployment evidence and independently trigger safe rollback."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from collections.abc import Iterable
from typing import Protocol

from app.metrics.collector import MetricSnapshot
from app.monitoring.workload_shift import total_variation_distance
from app.rollback.owned_index import RollbackRequest, RollbackResult, RollbackStatus
from app.workloads.snapshots import Share


@dataclass(frozen=True)
class MonitoringPolicy:
    """Configured production monitoring defaults, expressed in seconds/windows."""

    baseline_seconds: int = 10 * 60
    monitoring_seconds: int = 15 * 60
    window_seconds: int = 60
    sustained_regression_windows: int = 3
    protected_p99_regression_ratio: float = 1.20
    catastrophic_p99_ratio: float = 3.0
    workload_tvd_threshold: float = 0.20


DEFAULT_MONITORING_POLICY = MonitoringPolicy()


@dataclass(frozen=True)
class MonitoringWindow:
    """Literal-free metrics, workload, and replica health for one fixed window."""

    metrics: MetricSnapshot
    workload_distribution: tuple[Share, ...]
    replica_healthy: bool = True


class MonitoringStatus(str, Enum):
    """The operational outcome of independent monitoring."""

    STABLE = "STABLE"
    WORKLOAD_SHIFT_DETECTED = "WORKLOAD_SHIFT_DETECTED"
    ROLLED_BACK = "ROLLED_BACK"
    ROLLBACK_BLOCKED = "ROLLBACK_BLOCKED"


@dataclass(frozen=True)
class MonitoringDecision:
    """Computed safety facts; no caller may precompute or override these values."""

    catastrophic_p99: bool
    new_errors: bool
    new_timeouts: bool
    replica_unhealthy: bool
    sustained_protected_regression: bool
    workload_comparable: bool
    workload_shift_detected: bool

    @property
    def rollback_required(self) -> bool:
        return self.catastrophic_p99 or self.new_errors or self.new_timeouts or self.replica_unhealthy or (
            self.sustained_protected_regression and self.workload_comparable
        )


@dataclass(frozen=True)
class MonitoringResult:
    """Auditable monitoring output with every observed window and computed cause."""

    status: MonitoringStatus
    baseline: tuple[MonitoringWindow, ...]
    observed: tuple[MonitoringWindow, ...]
    decision: MonitoringDecision
    rollback_result: RollbackResult | None = None


class RollbackCoordinator(Protocol):
    """The monitor can invoke only ownership-verified rollback."""

    async def rollback(self, request: RollbackRequest) -> RollbackResult:
        """Attempt an ownership-verified rollback."""


class MonitoringEvidenceStore(Protocol):
    """Durable boundary for the monitor's raw windows and computed counters."""

    async def persist(self, result: MonitoringResult) -> None:
        """Persist literal-free monitoring evidence."""


class PostDeploymentMonitor:
    """Compute safety from telemetry windows and trigger only safe rollback."""

    def __init__(
        self,
        rollback_coordinator: RollbackCoordinator,
        policy: MonitoringPolicy = DEFAULT_MONITORING_POLICY,
        evidence_store: MonitoringEvidenceStore | None = None,
    ) -> None:
        if policy.baseline_seconds < policy.window_seconds or policy.monitoring_seconds < policy.window_seconds:
            raise ValueError("monitoring baseline and duration must contain at least one full window")
        if policy.sustained_regression_windows < 1:
            raise ValueError("sustained regression requires at least one window")
        self._rollback_coordinator = rollback_coordinator
        self._policy = policy
        self._evidence_store = evidence_store

    async def monitor(
        self,
        baseline: tuple[MonitoringWindow, ...],
        observed: tuple[MonitoringWindow, ...],
        rollback_request: RollbackRequest | None,
    ) -> MonitoringResult:
        """Independently decide whether deployed optimizer state must be rolled back."""
        self._validate_window_counts(baseline, observed)
        decision = self._decide(baseline, observed)
        if not decision.rollback_required:
            status = MonitoringStatus.WORKLOAD_SHIFT_DETECTED if decision.workload_shift_detected else MonitoringStatus.STABLE
            return await self._persist(MonitoringResult(status, baseline, observed, decision))
        if rollback_request is None:
            return await self._persist(MonitoringResult(MonitoringStatus.ROLLBACK_BLOCKED, baseline, observed, decision))
        rollback_result = await self._rollback_coordinator.rollback(rollback_request)
        status = MonitoringStatus.ROLLED_BACK if rollback_result.status is RollbackStatus.ROLLED_BACK else MonitoringStatus.ROLLBACK_BLOCKED
        return await self._persist(MonitoringResult(status, baseline, observed, decision, rollback_result))

    async def _persist(self, result: MonitoringResult) -> MonitoringResult:
        if self._evidence_store is not None:
            await self._evidence_store.persist(result)
        return result

    def _validate_window_counts(self, baseline: tuple[MonitoringWindow, ...], observed: tuple[MonitoringWindow, ...]) -> None:
        baseline_required = self._policy.baseline_seconds // self._policy.window_seconds
        monitoring_maximum = self._policy.monitoring_seconds // self._policy.window_seconds
        if len(baseline) < baseline_required:
            raise ValueError("insufficient predeployment baseline windows")
        if not observed or len(observed) > monitoring_maximum:
            raise ValueError("observed monitoring windows are outside the configured monitoring period")

    def _decide(self, baseline: tuple[MonitoringWindow, ...], observed: tuple[MonitoringWindow, ...]) -> MonitoringDecision:
        baseline_p99 = _average(window.metrics.p99_latency_ms for window in baseline)
        baseline_errors = max(window.metrics.error_count for window in baseline)
        baseline_timeouts = max(window.metrics.timeout_count for window in baseline)
        latest = observed[-1]
        workload_distance = total_variation_distance(baseline[-1].workload_distribution, latest.workload_distribution)
        comparable = workload_distance < self._policy.workload_tvd_threshold
        regression_windows = sum(
            _ratio(window.metrics.p99_latency_ms, baseline_p99) >= self._policy.protected_p99_regression_ratio
            for window in observed[-self._policy.sustained_regression_windows :]
        )
        return MonitoringDecision(
            catastrophic_p99=any(_ratio(window.metrics.p99_latency_ms, baseline_p99) >= self._policy.catastrophic_p99_ratio for window in observed),
            new_errors=any(window.metrics.error_count > baseline_errors for window in observed),
            new_timeouts=any(window.metrics.timeout_count > baseline_timeouts for window in observed),
            replica_unhealthy=any(not window.replica_healthy for window in observed),
            sustained_protected_regression=regression_windows >= self._policy.sustained_regression_windows,
            workload_comparable=comparable,
            workload_shift_detected=not comparable,
        )


def _average(values: Iterable[float | None]) -> float:
    numbers = [float(value) for value in values if value is not None]
    return sum(numbers) / len(numbers) if numbers else 0.0


def _ratio(value: float | None, baseline: float) -> float:
    if value is None:
        return 0.0
    return float("inf") if baseline <= 0 and value > 0 else value / baseline if baseline > 0 else 0.0
