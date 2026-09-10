"""Durable, immutable workload-snapshot materialization.

This module deliberately consumes completed PostgreSQL telemetry only.  MongoDB
collection is a separate concern and never occurs while its short transaction
is open.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db import models
from app.security.privacy import PrivacyBoundary, PrivacyMode


LOOKBACK_SECONDS = 900
MAX_SOURCE_AGE_SECONDS = 300


class SnapshotFailureCode(str, Enum):
    NO_COMPLETED_TELEMETRY = "NO_COMPLETED_TELEMETRY"
    STALE_TELEMETRY = "STALE_TELEMETRY"
    CROSS_TARGET_TELEMETRY = "CROSS_TARGET_TELEMETRY"
    SNAPSHOT_TARGET_MISMATCH = "SNAPSHOT_TARGET_MISMATCH"
    SNAPSHOT_RUN_MISMATCH = "SNAPSHOT_RUN_MISMATCH"
    SNAPSHOT_INTEGRITY_FAILURE = "SNAPSHOT_INTEGRITY_FAILURE"
    MALFORMED_SOURCE_EVIDENCE = "MALFORMED_SOURCE_EVIDENCE"
    PRIVACY_INVARIANT_FAILURE = "PRIVACY_INVARIANT_FAILURE"
    EMPTY_WORKLOAD = "EMPTY_WORKLOAD"


class WorkloadSnapshotError(RuntimeError):
    def __init__(self, code: SnapshotFailureCode, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code.value)


@dataclass(frozen=True)
class WorkloadSnapshotResult:
    snapshot_id: UUID
    reused: bool
    fingerprint: str


@dataclass(frozen=True)
class SnapshotRead:
    metadata: RowMapping
    source_windows: tuple[RowMapping, ...]
    query_shapes: tuple[RowMapping, ...]
    metrics: tuple[RowMapping, ...]


class WorkloadSnapshotService:
    """Create exactly one immutable materialization for a SNAPSHOTTING run."""

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        privacy: PrivacyBoundary | None = None,
        lookback_seconds: int = LOOKBACK_SECONDS,
        max_source_age_seconds: int = MAX_SOURCE_AGE_SECONDS,
        fail_after_parent: bool = False,
    ) -> None:
        self._engine = engine
        self._privacy = privacy or PrivacyBoundary(PrivacyMode.LOCAL_NORMALIZED)
        self._lookback = lookback_seconds
        self._max_age = max_source_age_seconds
        # Test-only fault injection exercises the same production transaction.
        self._fail_after_parent = fail_after_parent

    async def create_for_run(self, run_id: UUID) -> WorkloadSnapshotResult:
        """Materialize frozen completed telemetry and atomically attach it to `run_id`."""
        async with self._engine.begin() as connection:
            run = await self._locked_run(connection, run_id)
            attached = run["workload_snapshot_id"]
            if attached is not None:
                snapshot = await self._snapshot(connection, attached)
                if snapshot is None:
                    raise WorkloadSnapshotError(SnapshotFailureCode.SNAPSHOT_INTEGRITY_FAILURE)
                await self._validate_existing(connection, run, snapshot)
                return WorkloadSnapshotResult(snapshot["id"], True, snapshot["fingerprint"])
            if str(_value(run["status"])) != models.RunStatus.SNAPSHOTTING.value:
                raise WorkloadSnapshotError(SnapshotFailureCode.MALFORMED_SOURCE_EVIDENCE)

            windows, anchor = await self._select_source_windows(connection, run["target_id"])
            material = await self._build_material(connection, windows, run["target_id"], anchor, run_id)
            snapshot_id = uuid4()
            now = datetime.now(timezone.utc)
            await connection.execute(
                insert(models.WorkloadSnapshot.__table__).values(
                    id=snapshot_id, created_at=now, updated_at=now,
                    target_id=run["target_id"], telemetry_window_id=windows[-1]["id"],
                    source_run_id=run_id, observed_from=windows[0]["started_at"],
                    observed_until=anchor, anchor_at=anchor, snapshot=material["summary"],
                    completeness=material["completeness"], fingerprint=material["fingerprint"],
                )
            )
            if self._fail_after_parent:
                raise RuntimeError("injected snapshot materialization failure")
            for window in windows:
                await connection.execute(insert(models.WorkloadSnapshotSourceWindow.__table__).values(
                    id=uuid4(), created_at=now, updated_at=now, workload_snapshot_id=snapshot_id,
                    telemetry_window_id=window["id"],
                ))
            for evidence in material["shapes"]:
                await connection.execute(insert(models.WorkloadSnapshotQueryShape.__table__).values(
                    id=uuid4(), created_at=now, updated_at=now, workload_snapshot_id=snapshot_id, **evidence
                ))
            for metric in material["metrics"]:
                await connection.execute(insert(models.WorkloadSnapshotMetric.__table__).values(
                    id=uuid4(), created_at=now, updated_at=now, workload_snapshot_id=snapshot_id, **metric
                ))
            await connection.execute(update(models.OptimizationRun.__table__).where(
                models.OptimizationRun.__table__.c.id == run_id,
                models.OptimizationRun.__table__.c.workload_snapshot_id.is_(None),
            ).values(workload_snapshot_id=snapshot_id, updated_at=now))
            return WorkloadSnapshotResult(snapshot_id, False, material["fingerprint"])

    async def read(self, snapshot_id: UUID) -> SnapshotRead:
        async with self._engine.connect() as connection:
            snapshot = await self._snapshot(connection, snapshot_id)
            if snapshot is None:
                raise WorkloadSnapshotError(SnapshotFailureCode.SNAPSHOT_INTEGRITY_FAILURE)
            sources = tuple((await connection.execute(select(models.WorkloadSnapshotSourceWindow.__table__).where(models.WorkloadSnapshotSourceWindow.__table__.c.workload_snapshot_id == snapshot_id).order_by(models.WorkloadSnapshotSourceWindow.__table__.c.telemetry_window_id))).mappings().all())
            shapes = tuple((await connection.execute(select(models.WorkloadSnapshotQueryShape.__table__).where(models.WorkloadSnapshotQueryShape.__table__.c.workload_snapshot_id == snapshot_id).order_by(models.WorkloadSnapshotQueryShape.__table__.c.query_shape_hash))).mappings().all())
            metrics = tuple((await connection.execute(select(models.WorkloadSnapshotMetric.__table__).where(models.WorkloadSnapshotMetric.__table__.c.workload_snapshot_id == snapshot_id).order_by(models.WorkloadSnapshotMetric.__table__.c.source_metric_observation_id))).mappings().all())
            return SnapshotRead(snapshot, sources, shapes, metrics)

    async def verify_snapshot_integrity(self, snapshot_id: UUID) -> bool:
        view = await self.read(snapshot_id)
        canonical = _canonical({
            "target_id": str(view.metadata["target_id"]), "source_run_id": str(view.metadata["source_run_id"]),
            "observed_from": _timestamp(view.metadata["observed_from"]), "observed_until": _timestamp(view.metadata["observed_until"]),
            "anchor_at": _timestamp(view.metadata["anchor_at"]), "summary": view.metadata["snapshot"],
            "completeness": view.metadata["completeness"],
            "sources": [str(row["telemetry_window_id"]) for row in view.source_windows],
            "shapes": [_row_payload(row, _SHAPE_FIELDS) for row in view.query_shapes],
            "metrics": [_row_payload(row, _METRIC_FIELDS) for row in view.metrics],
        })
        persisted_fingerprint = str(view.metadata["fingerprint"])
        return hashlib.sha256(canonical.encode()).hexdigest() == persisted_fingerprint

    async def _locked_run(self, connection: AsyncConnection, run_id: UUID) -> RowMapping:
        row = (await connection.execute(select(models.OptimizationRun.__table__).where(models.OptimizationRun.__table__.c.id == run_id).with_for_update())).mappings().one_or_none()
        if row is None:
            raise WorkloadSnapshotError(SnapshotFailureCode.MALFORMED_SOURCE_EVIDENCE)
        return row

    async def _snapshot(self, connection: AsyncConnection, snapshot_id: UUID) -> RowMapping | None:
        return (await connection.execute(select(models.WorkloadSnapshot.__table__).where(models.WorkloadSnapshot.__table__.c.id == snapshot_id))).mappings().one_or_none()

    async def _validate_existing(self, connection: AsyncConnection, run: RowMapping, snapshot: RowMapping) -> None:
        if snapshot["source_run_id"] != run["id"]:
            raise WorkloadSnapshotError(SnapshotFailureCode.SNAPSHOT_RUN_MISMATCH)
        if snapshot["target_id"] != run["target_id"]:
            raise WorkloadSnapshotError(SnapshotFailureCode.SNAPSHOT_TARGET_MISMATCH)
        sources = (await connection.execute(select(models.WorkloadSnapshotSourceWindow.__table__.c.telemetry_window_id).where(models.WorkloadSnapshotSourceWindow.__table__.c.workload_snapshot_id == snapshot["id"]))).all()
        if not sources or not await self.verify_snapshot_integrity(snapshot["id"]):
            raise WorkloadSnapshotError(SnapshotFailureCode.SNAPSHOT_INTEGRITY_FAILURE)

    async def _select_source_windows(self, connection: AsyncConnection, target_id: UUID) -> tuple[tuple[RowMapping, ...], datetime]:
        table = models.TelemetryWindow.__table__
        newest = (await connection.execute(select(table).where(table.c.target_id == target_id, table.c.status == "COMPLETED").order_by(table.c.ended_at.desc(), table.c.id.desc()).limit(1))).mappings().one_or_none()
        if newest is None:
            raise WorkloadSnapshotError(SnapshotFailureCode.NO_COMPLETED_TELEMETRY, retryable=True)
        anchor = newest["ended_at"]
        if datetime.now(timezone.utc) - anchor > timedelta(seconds=self._max_age):
            raise WorkloadSnapshotError(SnapshotFailureCode.STALE_TELEMETRY, retryable=True)
        rows = tuple((await connection.execute(select(table).where(
            table.c.target_id == target_id, table.c.status == "COMPLETED",
            table.c.started_at >= anchor - timedelta(seconds=self._lookback), table.c.ended_at <= anchor,
        ).order_by(table.c.started_at, table.c.id))).mappings().all())
        if not rows:
            raise WorkloadSnapshotError(SnapshotFailureCode.NO_COMPLETED_TELEMETRY, retryable=True)
        return rows, anchor

    async def _build_material(self, connection: AsyncConnection, windows: tuple[RowMapping, ...], target_id: UUID, anchor: datetime, run_id: UUID) -> dict[str, Any]:
        ids = [row["id"] for row in windows]
        metrics_rows = tuple((await connection.execute(select(
            models.MetricObservation.__table__, models.QueryShape.__table__.c.shape_hash,
            models.QueryShape.__table__.c.operation, models.Namespace.__table__.c.name.label("namespace"),
        ).select_from(models.MetricObservation.__table__.outerjoin(models.QueryShape.__table__, models.MetricObservation.__table__.c.query_shape_id == models.QueryShape.__table__.c.id).outerjoin(models.Namespace.__table__, models.QueryShape.__table__.c.namespace_id == models.Namespace.__table__.c.id)).where(models.MetricObservation.__table__.c.telemetry_window_id.in_(ids)))).mappings().all())
        # This explicit target check fails closed even if a corrupt foreign-key graph appears.
        source_targets = {row["target_id"] for row in windows}
        if source_targets != {target_id}:
            raise WorkloadSnapshotError(SnapshotFailureCode.CROSS_TARGET_TELEMETRY)
        grouped: dict[UUID, dict[str, Any]] = {}
        frozen_metrics: list[dict[str, Any]] = []
        providers = sorted({str(row["source"]) for row in windows})
        for row in metrics_rows:
            scope = "QUERY_SHAPE" if row["query_shape_id"] is not None else "GLOBAL"
            frozen_metrics.append({"source_metric_observation_id": row["id"], "scope": scope, "metric_name": row["metric_name"], "metric_value": float(row["metric_value"])})
            shape_id = row["query_shape_id"]
            if shape_id is None:
                continue
            data = grouped.setdefault(shape_id, {"query_shape_id": shape_id, "query_shape_hash": row["shape_hash"], "operation": row["operation"], "namespace": self._privacy.pseudonymize_identifier(row["namespace"]), "operation_count": None, "success": None, "failure": None, "timeout": None, "execution": None, "manual": False})
            name, value = row["metric_name"], float(row["metric_value"])
            if name == "operation_count":
                data["operation_count"] = (data["operation_count"] or 0) + int(value)
            elif name == "successful_operation_count":
                data["success"] = (data["success"] or 0) + int(value)
            elif name == "failure_count":
                data["failure"] = (data["failure"] or 0) + int(value)
            elif name == "timeout_count":
                data["timeout"] = (data["timeout"] or 0) + int(value)
            elif name == "aggregate_execution_time_ms":
                data["execution"] = (data["execution"] or 0.0) + value
            elif name == "manually_critical":
                data["manual"] = data["manual"] or value > 0
        shapes_with_count = [item for item in grouped.values() if item["operation_count"] is not None]
        total = sum(item["operation_count"] for item in shapes_with_count)
        if total <= 0:
            raise WorkloadSnapshotError(SnapshotFailureCode.EMPTY_WORKLOAD)
        total_execution = sum(item["execution"] or 0.0 for item in shapes_with_count)
        shapes: list[dict[str, Any]] = []
        for item in sorted(shapes_with_count, key=lambda value: value["query_shape_hash"]):
            operation_share = item["operation_count"] / total
            execution_share = (item["execution"] / total_execution) if item["execution"] is not None and total_execution > 0 else None
            manual, by_operation, by_execution = item["manual"], operation_share >= .01, execution_share is not None and execution_share >= .01
            shapes.append({"query_shape_id": item["query_shape_id"], "query_shape_hash": item["query_shape_hash"], "operation": item["operation"], "namespace": item["namespace"], "observed_operation_count": item["operation_count"], "successful_operation_count": item["success"], "failure_count": item["failure"], "timeout_count": item["timeout"], "aggregate_execution_time_ms": item["execution"], "workload_operation_share": operation_share, "execution_time_share": execution_share, "manually_critical": manual, "protected_manual_critical": manual, "protected_operation_share": by_operation, "protected_execution_time_share": by_execution, "base_protected": bool(manual or by_operation or by_execution), "provider": ",".join(providers)})
        frozen_metrics.sort(key=lambda value: str(value["source_metric_observation_id"]))
        available = sorted({row["metric_name"] for row in metrics_rows})
        completeness = {"query_shapes_available": bool(shapes), "workload_counts_available": bool(shapes_with_count), "available_metric_keys": available, "missing_metric_families": [name for name in ("successful_operation_count", "failure_count", "timeout_count", "aggregate_execution_time_ms") if name not in available], "providers": providers, "production_autonomy_eligible": providers != ["CURRENT_OP"]}
        summary = {"source_provider": providers, "source_window_count": len(windows), "query_shape_count": len(shapes), "operation_count": total, "execution_time_ms": total_execution if total_execution else None}
        digest_input = {"target_id": str(target_id), "source_run_id": str(run_id), "observed_from": _timestamp(windows[0]["started_at"]), "observed_until": _timestamp(anchor), "anchor_at": _timestamp(anchor), "summary": summary, "completeness": completeness, "sources": sorted(str(row["id"]) for row in windows), "shapes": shapes, "metrics": frozen_metrics}
        return {"summary": summary, "completeness": completeness, "shapes": shapes, "metrics": frozen_metrics, "fingerprint": hashlib.sha256(_canonical(digest_input).encode()).hexdigest()}


_SHAPE_FIELDS = ("query_shape_id", "query_shape_hash", "operation", "namespace", "observed_operation_count", "successful_operation_count", "failure_count", "timeout_count", "aggregate_execution_time_ms", "workload_operation_share", "execution_time_share", "manually_critical", "protected_manual_critical", "protected_operation_share", "protected_execution_time_share", "base_protected", "provider")
_METRIC_FIELDS = ("source_metric_observation_id", "scope", "metric_name", "metric_value")


def _value(value: object) -> object:
    return value.value if hasattr(value, "value") else value


def _timestamp(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


def _row_payload(row: RowMapping, fields: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in fields:
        value = row[field]
        result[field] = str(value) if isinstance(value, UUID) else float(value) if hasattr(value, "as_tuple") else value
    return result


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
