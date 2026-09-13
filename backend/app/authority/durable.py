"""Immutable authority decisions for admitted durable candidates."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine

from app.autonomy.policy import DeploymentMode
from app.db import models


AUTONOMY_INELIGIBLE_REQUIRES_APPROVAL = "AUTONOMY_INELIGIBLE_REQUIRES_APPROVAL"


@dataclass(frozen=True)
class AuthorityResult:
    decision: RowMapping
    automatic: bool


class AuthorityInvariantError(ValueError):
    """The persisted admission/candidate evidence cannot safely authorize work."""


class DurableAuthorityService:
    """Create exactly one immutable authority artifact for an admitted run."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def decide_for_run(self, run_id: UUID) -> AuthorityResult:
        async with self._engine.begin() as connection:
            existing = (
                await connection.execute(
                    select(models.AuthorityDecision.__table__).where(
                        models.AuthorityDecision.__table__.c.optimization_run_id == run_id
                    )
                )
            ).mappings().one_or_none()
            if existing is not None:
                return AuthorityResult(existing, existing["authority_type"] == "AUTONOMOUS")

            run = (
                await connection.execute(
                    select(models.OptimizationRun.__table__).where(models.OptimizationRun.__table__.c.id == run_id).with_for_update()
                )
            ).mappings().one_or_none()
            if run is None or _enum_value(run["status"]) != models.RunStatus.ADMITTED.value:
                raise AuthorityInvariantError("authority requires an admitted run")
            admission = (
                await connection.execute(
                    select(models.AdmissionArtifact.__table__).where(models.AdmissionArtifact.__table__.c.optimization_run_id == run_id)
                )
            ).mappings().one_or_none()
            if admission is None or admission["selected_candidate_id"] is None:
                raise AuthorityInvariantError("authority requires an immutable selected admitted candidate")
            candidate = (
                await connection.execute(
                    select(models.Candidate.__table__).where(models.Candidate.__table__.c.id == admission["selected_candidate_id"])
                )
            ).mappings().one_or_none()
            if candidate is None or candidate["deterministic_fingerprint"] is None:
                raise AuthorityInvariantError("selected candidate lacks an immutable fingerprint")
            action = (
                await connection.execute(
                    select(models.CandidateAction.__table__).where(models.CandidateAction.__table__.c.candidate_id == candidate["id"])
                )
            ).mappings().one_or_none()
            snapshot = (
                await connection.execute(
                    select(models.WorkloadSnapshot.__table__.c.completeness).where(models.WorkloadSnapshot.__table__.c.id == run["workload_snapshot_id"])
                )
            ).scalar_one_or_none()
            if action is None or not isinstance(snapshot, dict):
                raise AuthorityInvariantError("authority evidence is incomplete")
            mode = DeploymentMode(str(run["deployment_mode"]))
            eligible = bool(snapshot.get("completeness", {}).get("production_autonomy_eligible", False))
            action_type = str(action["action_type"])
            automatic = (
                mode is DeploymentMode.FULL_AUTONOMOUS
                and eligible
                and candidate["policy_classification"] == "AUTO_ELIGIBLE_AFTER_ADMISSION"
                and action_type in {"CREATE_INDEX", "SET_QUERY_SETTINGS_INDEX_HINT"}
            )
            authority_type = "AUTONOMOUS" if automatic else "HUMAN_REQUIRED"
            reason = "AUTONOMY_ELIGIBLE" if automatic else AUTONOMY_INELIGIBLE_REQUIRES_APPROVAL
            fingerprint = _fingerprint(
                run_id, candidate["id"], candidate["deterministic_fingerprint"], mode.value, authority_type, reason, eligible
            )
            values = {
                "id": uuid4(),
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                "optimization_run_id": run_id,
                "candidate_id": candidate["id"],
                "candidate_fingerprint": candidate["deterministic_fingerprint"],
                "deployment_mode": mode.value,
                "authority_type": authority_type,
                "authority_reason": reason,
                "production_autonomy_eligible": eligible,
                "integrity_fingerprint": fingerprint,
            }
            decision = (await connection.execute(insert(models.AuthorityDecision.__table__).values(**values).returning(*models.AuthorityDecision.__table__.c))).mappings().one()
            return AuthorityResult(decision, automatic)


def _enum_value(value: object) -> str:
    return str(value.value if hasattr(value, "value") else value)


def _fingerprint(*values: object) -> str:
    encoded = json.dumps([str(value) for value in values], separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()
