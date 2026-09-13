"""Durable calibration plan and trial evidence persistence for R19I."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.admission.models import BenchmarkProfile
from app.admission.policy import PROFILES
from app.db import models
from app.db.repositories import EvaluationPlanRepository, EvaluationRepository, TrialMetricRepository, TrialPairRepository


class EvaluationPlanError(ValueError):
    """A persisted ranking cannot safely define controlled evaluation work."""


@dataclass(frozen=True)
class EvaluationPlanResult:
    plan_id: UUID
    selected_candidate_ids: tuple[UUID, ...]
    profile: BenchmarkProfile


class DurableEvaluationService:
    """Freeze ranked selection before benchmarks and persist pair observations idempotently."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create_plan_for_run(self, run_id: UUID, profile: BenchmarkProfile, calibration: dict[str, object]) -> EvaluationPlanResult:
        async with self._engine.begin() as connection:
            existing = (await connection.execute(select(models.EvaluationPlan.__table__).where(models.EvaluationPlan.__table__.c.optimization_run_id == run_id).with_for_update())).mappings().one_or_none()
            if existing is not None:
                return EvaluationPlanResult(existing["id"], tuple(UUID(value) for value in existing["selected_candidate_ids"]), BenchmarkProfile(existing["profile"]))
            ranking = (await connection.execute(select(models.CandidateRankingArtifact.__table__).where(models.CandidateRankingArtifact.__table__.c.optimization_run_id == run_id))).mappings().one_or_none()
            if ranking is None:
                raise EvaluationPlanError("valid durable ranking is required before calibration")
            selected = list(ranking["ordered_candidate_ids"][: min(3, len(ranking["ordered_candidate_ids"]))])
            if not selected:
                raise EvaluationPlanError("evaluation plan cannot be empty")
            settings = PROFILES[profile]
            required = {"profile": profile.value, "warmup_seconds": settings.warmup_seconds, "measurement_seconds": settings.measurement_seconds, "bootstrap_samples": settings.bootstrap_samples, **calibration}
            fingerprint = _hash({"run_id": str(run_id), "ranking": str(ranking["id"]), "selected": selected, "calibration": required})
            row = await EvaluationPlanRepository(self._engine).create_in_transaction(connection, optimization_run_id=run_id, ranking_artifact_id=ranking["id"], profile=profile.value, selected_candidate_ids=selected, calibration=required, artifact_fingerprint=fingerprint)
            return EvaluationPlanResult(row["id"], tuple(UUID(value) for value in selected), profile)

    async def record_pair(self, candidate_id: UUID, pair_number: int, environment_fingerprint: str, baseline: dict[str, float], candidate: dict[str, float], arm_order: str) -> UUID:
        """Persist one measured AB/BA pair; retries reuse the exact pair number."""
        if arm_order not in {"AB", "BA"}:
            raise EvaluationPlanError("trial arm order must be AB or BA")
        async with self._engine.begin() as connection:
            evaluation = (await connection.execute(select(models.EvaluationRun.__table__).where(models.EvaluationRun.__table__.c.candidate_id == candidate_id).with_for_update())).mappings().one_or_none()
            if evaluation is None:
                evaluation = await EvaluationRepository(self._engine).create_in_transaction(connection, candidate_id=candidate_id, status="MEASURING", environment_fingerprint=environment_fingerprint)
            pair = (await connection.execute(select(models.TrialPair.__table__).where(models.TrialPair.__table__.c.evaluation_run_id == evaluation["id"], models.TrialPair.__table__.c.pair_number == pair_number))).mappings().one_or_none()
            if pair is not None:
                return cast(UUID, pair["id"])
            pair = await TrialPairRepository(self._engine).create_in_transaction(connection, evaluation_run_id=evaluation["id"], pair_number=pair_number, baseline_measurement={"metrics": baseline, "arm_order": arm_order}, candidate_measurement={"metrics": candidate, "arm_order": arm_order})
            for metric_name in sorted(set(baseline) | set(candidate)):
                if metric_name not in baseline or metric_name not in candidate:
                    continue
                await TrialMetricRepository(self._engine).create_in_transaction(connection, trial_pair_id=pair["id"], metric_name=metric_name, baseline_value=baseline[metric_name], candidate_value=candidate[metric_name])
            return cast(UUID, pair["id"])

    async def mark_complete(self, candidate_id: UUID) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(models.EvaluationRun.__table__.update().where(models.EvaluationRun.__table__.c.candidate_id == candidate_id).values(status="COMPLETED", updated_at=datetime.now(timezone.utc)))


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
