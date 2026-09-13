"""Run-bound monitoring that persists measured evidence before terminal state."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.db.repositories import AuditRepository
from app.db import models
from app.db.repositories import ExperienceRepository
from app.monitoring.post_deployment import MonitoringResult, MonitoringWindow, PostDeploymentMonitor
from app.rollback.durable import DurableRollbackService
from app.rollback.owned_index import RollbackRequest, RollbackResult, RollbackStatus


class MonitoringEvidenceUnavailable(RuntimeError):
    """Telemetry was transiently unavailable; retain MONITORING for retry."""


class DurableMonitoringService:
    """Collect real windows, persist them, and invoke only safe durable rollback."""

    def __init__(
        self,
        engine: Any,
        collect_windows: Callable[[UUID], Awaitable[tuple[tuple[MonitoringWindow, ...], tuple[MonitoringWindow, ...]]]],
        rollback: DurableRollbackService,
    ) -> None:
        self._engine = engine
        self._collect_windows = collect_windows
        self._rollback = rollback

    async def monitor_for_run(self, run_id: UUID) -> MonitoringResult:
        try:
            baseline, observed = await self._collect_windows(run_id)
        except (OSError, TimeoutError) as error:
            raise MonitoringEvidenceUnavailable("MONITORING_TELEMETRY_UNAVAILABLE") from error

        class _Coordinator:
            async def rollback(_self, request: RollbackRequest) -> RollbackResult:
                status, reason = await self._rollback.rollback_for_run(run_id)
                return RollbackResult(
                    RollbackStatus.ROLLED_BACK if status.value == "ROLLED_BACK" else RollbackStatus.ROLLBACK_BLOCKED,
                    () if status.value == "ROLLED_BACK" else (reason,),
                )

        # A request is only an opaque trigger; ownership is re-derived from the
        # durable deployment artifact before any inverse mutation.
        monitor = PostDeploymentMonitor(_Coordinator())
        result = await monitor.monitor(baseline, observed, RollbackRequest("durable", str(run_id), "durable-monitor"))
        await AuditRepository(self._engine).create(
            actor_user_id=None,
            optimization_run_id=run_id,
            event_type="DURABLE_POST_DEPLOYMENT_MONITORING",
            event_payload={
                "status": result.status.value,
                "baseline_windows": [_window(window) for window in result.baseline],
                "observed_windows": [_window(window) for window in result.observed],
                "rollback_required": result.decision.rollback_required,
            },
        )
        # Terminal factual outcome persistence is intentionally independent of
        # embedding generation. Embeddings can be added later by recoverable
        # secondary work; terminal safety never waits on model availability.
        if result.status.value in {"STABLE", "WORKLOAD_SHIFT_DETECTED", "ROLLED_BACK", "ROLLBACK_BLOCKED"}:
            from sqlalchemy import select

            async with self._engine.connect() as connection:
                candidate = await connection.scalar(
                    select(models.DeploymentArtifact.__table__.c.candidate_id).where(
                        models.DeploymentArtifact.__table__.c.optimization_run_id == run_id
                    )
                )
            if candidate is not None:
                outcome = "DEPLOYMENT_SUCCEEDED" if result.status.value in {"STABLE", "WORKLOAD_SHIFT_DETECTED"} else result.status.value
                async with self._engine.connect() as connection:
                    already_recorded = await connection.scalar(
                        select(models.ExperienceRecord.__table__.c.id).where(
                            models.ExperienceRecord.__table__.c.candidate_id == candidate,
                            models.ExperienceRecord.__table__.c.outcome == outcome,
                        )
                    )
                if already_recorded is None:
                    await ExperienceRepository(self._engine).create(
                        candidate_id=candidate,
                        outcome=outcome,
                        embedding=None,
                        evidence={"monitoring_status": result.status.value, "rollback_required": result.decision.rollback_required},
                        adapter_type="mongodb", action_type="CREATE_INDEX", query_structure_summary={}, workload_features={},
                        bottleneck=None, candidate_summary={}, prediction={}, admission_outcome="ADMITTED",
                        actual_postdeploy_outcome=result.status.value,
                        rollback_outcome=result.rollback_result.status.value if result.rollback_result is not None else None,
                        embedding_model="embeddinggemma", embedding_model_version="deferred",
                    )
        return result


def _window(window: MonitoringWindow) -> dict[str, object]:
    return {
        "p50_latency_ms": window.metrics.p50_latency_ms,
        "p95_latency_ms": window.metrics.p95_latency_ms,
        "p99_latency_ms": window.metrics.p99_latency_ms,
        "error_count": window.metrics.error_count,
        "timeout_count": window.metrics.timeout_count,
        "replica_healthy": window.replica_healthy,
        "workload": [{"name": part.name, "fraction": part.fraction} for part in window.workload_distribution],
    }
