"""Phase 34 acceptance tests for monitoring and rollback coordination."""

import pytest

from app.metrics.collector import MetricSnapshot
from app.monitoring.post_deployment import MonitoringStatus, MonitoringWindow, PostDeploymentMonitor
from app.rollback.owned_index import RollbackRequest, RollbackResult, RollbackStatus
from app.workloads.snapshots import Share


class SpyRollbackCoordinator:
    def __init__(self, result: RollbackResult) -> None:
        self.result = result
        self.requests: list[RollbackRequest] = []

    async def rollback(self, request: RollbackRequest) -> RollbackResult:
        self.requests.append(request)
        return self.result


def _window() -> MonitoringWindow:
    metrics = MetricSnapshot(10, 20, 30, 100, 80, 20, 1, 2, 3, 4, 5, 0, 10, 9, 8, 7, 0, 0)
    return MonitoringWindow(metrics, (Share("shape-a", 1.0),))


@pytest.mark.asyncio
async def test_stable_monitoring_retains_all_required_evidence() -> None:
    monitor = PostDeploymentMonitor(SpyRollbackCoordinator(RollbackResult(RollbackStatus.ROLLED_BACK, ())))

    result = await monitor.assess(_window(), _window(), False, False, None)

    assert result.status is MonitoringStatus.STABLE
    assert result.observed.metrics.p99_latency_ms == 30
    assert result.observed.metrics.throughput_per_second == 100
    assert result.observed.metrics.error_count == 0
    assert result.observed.metrics.timeout_count == 0
    assert result.observed.metrics.replication_lag_seconds == 0
    assert result.observed.workload_distribution == (Share("shape-a", 1.0),)


@pytest.mark.asyncio
async def test_workload_shift_withholds_statistical_attribution_without_rollback() -> None:
    rollback = SpyRollbackCoordinator(RollbackResult(RollbackStatus.ROLLED_BACK, ()))
    monitor = PostDeploymentMonitor(rollback)

    result = await monitor.assess(_window(), _window(), False, True, None)

    assert result.status is MonitoringStatus.WORKLOAD_SHIFT_DETECTED
    assert result.attribution == "WORKLOAD_SHIFT"
    assert rollback.requests == []


@pytest.mark.asyncio
async def test_catastrophic_regression_triggers_owned_rollback_even_with_workload_shift() -> None:
    request = RollbackRequest("target-1", "ledger-entry-1", "monitor")
    rollback = SpyRollbackCoordinator(RollbackResult(RollbackStatus.ROLLED_BACK, ()))
    monitor = PostDeploymentMonitor(rollback)

    result = await monitor.assess(_window(), _window(), True, True, request)

    assert result.status is MonitoringStatus.ROLLED_BACK
    assert result.attribution == "WORKLOAD_SHIFT"
    assert rollback.requests == [request]
