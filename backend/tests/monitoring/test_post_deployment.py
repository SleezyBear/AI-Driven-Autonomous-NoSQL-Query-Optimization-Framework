"""R18 acceptance tests for monitor-owned post-deployment safety decisions."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.repositories import AuditRepository
from app.metrics.collector import MetricSnapshot
from app.monitoring.persistence import PostgresMonitoringEvidenceStore
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


def _window(p99: float = 30, errors: int = 0, timeouts: int = 0, replica_healthy: bool = True) -> MonitoringWindow:
    metrics = MetricSnapshot(10, 20, p99, 100, 80, 20, 1, 2, 3, 4, 5, 0, 10, 9, 8, 7, errors, timeouts)
    return MonitoringWindow(metrics, (Share("shape-a", 1.0),), replica_healthy)


def _baseline() -> tuple[MonitoringWindow, ...]:
    return (_window(),) * 10


@pytest.mark.asyncio
async def test_stable_monitoring_computes_safe_decision_without_external_flags() -> None:
    monitor = PostDeploymentMonitor(SpyRollbackCoordinator(RollbackResult(RollbackStatus.ROLLED_BACK, ())))

    result = await monitor.monitor(_baseline(), (_window(),), None)

    assert result.status is MonitoringStatus.STABLE
    assert not result.decision.rollback_required
    assert result.observed[-1].metrics.p99_latency_ms == 30


@pytest.mark.asyncio
async def test_controlled_three_times_p99_regression_independently_triggers_owned_rollback() -> None:
    request = RollbackRequest("target-1", "ledger-entry-1", "monitor")
    rollback = SpyRollbackCoordinator(RollbackResult(RollbackStatus.ROLLED_BACK, ()))
    monitor = PostDeploymentMonitor(rollback)

    result = await monitor.monitor(_baseline(), (_window(p99=90),), request)

    assert result.decision.catastrophic_p99
    assert result.decision.rollback_required
    assert result.status is MonitoringStatus.ROLLED_BACK
    assert rollback.requests == [request]


@pytest.mark.asyncio
async def test_three_comparable_protected_regressions_trigger_rollback() -> None:
    request = RollbackRequest("target-1", "ledger-entry-1", "monitor")
    rollback = SpyRollbackCoordinator(RollbackResult(RollbackStatus.ROLLED_BACK, ()))
    monitor = PostDeploymentMonitor(rollback)

    result = await monitor.monitor(_baseline(), (_window(p99=40), _window(p99=40), _window(p99=40)), request)

    assert result.decision.sustained_protected_regression
    assert result.decision.workload_comparable
    assert result.status is MonitoringStatus.ROLLED_BACK


@pytest.mark.asyncio
async def test_new_errors_timeouts_or_replica_failure_are_computed_as_rollback_causes() -> None:
    request = RollbackRequest("target-1", "ledger-entry-1", "monitor")
    rollback = SpyRollbackCoordinator(RollbackResult(RollbackStatus.ROLLED_BACK, ()))
    monitor = PostDeploymentMonitor(rollback)

    result = await monitor.monitor(_baseline(), (_window(errors=1, timeouts=1, replica_healthy=False),), request)

    assert result.decision.new_errors
    assert result.decision.new_timeouts
    assert result.decision.replica_unhealthy
    assert result.status is MonitoringStatus.ROLLED_BACK


@pytest.mark.asyncio
async def test_monitor_persists_raw_windows_and_computed_counters_to_postgres(disposable_monitoring_database: str) -> None:
    engine = create_async_engine(disposable_monitoring_database)
    record_id = None
    try:
        monitor = PostDeploymentMonitor(
            SpyRollbackCoordinator(RollbackResult(RollbackStatus.ROLLED_BACK, ())),
            evidence_store=PostgresMonitoringEvidenceStore(AuditRepository(engine)),
        )
        await monitor.monitor(_baseline(), (_window(),), None)
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT id, event_payload FROM audit_events WHERE event_type = 'POST_DEPLOYMENT_MONITORING_WINDOW' ORDER BY created_at DESC LIMIT 1"))
            record_id, payload = result.one()
        assert payload["observed"][0]["p99_latency_ms"] == 30
        assert payload["decision"]["catastrophic_p99"] is False
    finally:
        if record_id is not None:
            async with engine.begin() as connection:
                await connection.execute(text("DELETE FROM audit_events WHERE id = :id"), {"id": record_id})
        await engine.dispose()
