"""Persist literal-free observations emitted by the real telemetry providers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import models
from app.query_shapes.registry import QueryShapeRegistry
from app.security.privacy import PrivacyBoundary, PrivacyMode
from app.telemetry.providers import TelemetryObservation, TelemetryProvider


class TelemetryPersistenceService:
    """Collect outside PostgreSQL, then atomically persist a completed window."""

    def __init__(self, engine: AsyncEngine, *, privacy: PrivacyBoundary | None = None) -> None:
        self._engine = engine
        self._privacy = privacy or PrivacyBoundary(PrivacyMode.LOCAL_NORMALIZED)

    async def collect_and_persist(self, target_id: UUID, provider: TelemetryProvider) -> UUID:
        """Use an existing real provider; no profiler state is changed here."""
        observations = await provider.collect()
        return await self.persist_completed(target_id, provider.source.value, observations)

    async def persist_completed(
        self,
        target_id: UUID,
        source: str,
        observations: tuple[TelemetryObservation, ...],
        *,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> UUID:
        """Persist the provider's literal-free operation-count observations."""
        started = started_at or datetime.now(timezone.utc)
        ended = ended_at or datetime.now(timezone.utc)
        now = datetime.now(timezone.utc)
        registry = QueryShapeRegistry()
        window_id = uuid4()
        async with self._engine.begin() as connection:
            await connection.execute(insert(models.TelemetryWindow.__table__).values(
                id=window_id, created_at=now, updated_at=now, target_id=target_id,
                started_at=started, ended_at=ended, source=source, status="COMPLETED",
            ))
            for observation in observations:
                database = self._privacy.pseudonymize_identifier(observation.database)
                collection = self._privacy.pseudonymize_identifier(observation.collection)
                namespace_name = f"{database}.{collection}"
                namespace = (await connection.execute(select(models.Namespace.__table__).where(
                    models.Namespace.__table__.c.target_id == target_id,
                    models.Namespace.__table__.c.name == namespace_name,
                ))).mappings().one_or_none()
                if namespace is None:
                    namespace_id = uuid4()
                    await connection.execute(insert(models.Namespace.__table__).values(
                        id=namespace_id, created_at=now, updated_at=now, target_id=target_id,
                        name=namespace_name, allowlisted=False,
                    ))
                else:
                    namespace_id = namespace["id"]
                shape = registry.register(observation.operation, namespace_name, observation.normalized_shape)
                existing = (await connection.execute(select(models.QueryShape.__table__).where(
                    models.QueryShape.__table__.c.namespace_id == namespace_id,
                    models.QueryShape.__table__.c.shape_hash == shape.shape_hash,
                ))).mappings().one_or_none()
                if existing is None:
                    shape_id = uuid4()
                    await connection.execute(insert(models.QueryShape.__table__).values(
                        id=shape_id, created_at=now, updated_at=now, namespace_id=namespace_id,
                        shape_hash=shape.shape_hash, normalized_shape=json.loads(shape.canonical_shape),
                        operation=observation.operation,
                    ))
                else:
                    shape_id = existing["id"]
                metrics: tuple[tuple[str, int | float | None], ...] = (
                    ("operation_count", observation.operation_count),
                    (
                        "successful_operation_count",
                        observation.successful_operation_count,
                    ),
                    ("failure_count", observation.failure_count),
                    ("timeout_count", observation.timeout_count),
                    (
                        "aggregate_execution_time_ms",
                        observation.aggregate_execution_time_ms,
                    ),
                )
                for metric_name, metric_value in metrics:
                    if metric_value is None:
                        continue
                    await connection.execute(
                        insert(models.MetricObservation.__table__).values(
                            id=uuid4(),
                            created_at=now,
                            updated_at=now,
                            telemetry_window_id=window_id,
                            query_shape_id=shape_id,
                            metric_name=metric_name,
                            metric_value=metric_value,
                            observed_at=ended,
                        )
                    )
        return window_id
