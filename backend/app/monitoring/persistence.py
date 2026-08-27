"""PostgreSQL persistence for post-deployment monitoring evidence."""

from __future__ import annotations

from typing import Any

from app.db.repositories import AuditRepository
from app.monitoring.post_deployment import MonitoringResult


class PostgresMonitoringEvidenceStore:
    """Append literal-free raw monitoring windows and computed causes to PostgreSQL."""

    def __init__(self, audit_repository: AuditRepository) -> None:
        self._audit_repository = audit_repository

    async def persist(self, result: MonitoringResult) -> None:
        await self._audit_repository.create(
            actor_user_id=None,
            optimization_run_id=None,
            event_type="POST_DEPLOYMENT_MONITORING_WINDOW",
            event_payload={
                "status": result.status.value,
                "baseline": [_window_payload(window) for window in result.baseline],
                "observed": [_window_payload(window) for window in result.observed],
                "decision": {
                    "catastrophic_p99": result.decision.catastrophic_p99,
                    "new_errors": result.decision.new_errors,
                    "new_timeouts": result.decision.new_timeouts,
                    "replica_unhealthy": result.decision.replica_unhealthy,
                    "sustained_protected_regression": result.decision.sustained_protected_regression,
                    "workload_comparable": result.decision.workload_comparable,
                },
            },
        )


def _window_payload(window: Any) -> dict[str, object]:
    metrics = window.metrics
    return {
        "p50_latency_ms": metrics.p50_latency_ms,
        "p95_latency_ms": metrics.p95_latency_ms,
        "p99_latency_ms": metrics.p99_latency_ms,
        "error_count": metrics.error_count,
        "timeout_count": metrics.timeout_count,
        "replica_healthy": window.replica_healthy,
        "workload_distribution": [{"name": share.name, "fraction": share.fraction} for share in window.workload_distribution],
    }
