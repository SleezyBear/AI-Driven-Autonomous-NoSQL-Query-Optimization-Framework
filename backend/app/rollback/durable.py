"""Durable, ownership-verified rollback for a run-bound deployment artifact."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping, cast
from uuid import UUID, uuid4

from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.actions.schemas import CreateIndexAction, DropIndexAction
from app.adapters.contracts import DatabaseAdapter, Namespace
from app.db import models
from app.ledger.postgres import PostgresProductionLedger
from app.production.target_lock import PostgresTargetMutationLock


class DurableRollbackService:
    """Drop only the exact index created by the matching durable artifact."""

    def __init__(self, engine: AsyncEngine, adapter: DatabaseAdapter, *, actor: str = "durable-rollback-worker") -> None:
        self._engine = engine
        self._adapter = adapter
        self._locks = PostgresTargetMutationLock(engine)
        self._ledger = PostgresProductionLedger(engine)
        self._actor = actor

    async def rollback_for_run(self, run_id: UUID) -> tuple[models.RunStatus, str]:
        bound = await self._bound(run_id)
        # A recorded rollback outcome is terminal factual evidence.  Replaying
        # a recovered job must return that fact rather than inspecting (and
        # potentially acting on) an already-reverted external resource.
        recorded = await self._recorded_outcome(bound["candidate_id"])
        if recorded is not None:
            return recorded
        lease = await self._locks.try_acquire(bound["target_id"])
        if lease is None:
            return models.RunStatus.ROLLBACK_BLOCKED, "TARGET_LOCK_UNAVAILABLE"
        try:
            return await self._rollback_locked(bound)
        finally:
            await lease.release()

    async def _rollback_locked(self, bound: Mapping[str, Any]) -> tuple[models.RunStatus, str]:
        action = CreateIndexAction.model_validate(bound["action_payload"])
        state = await self._state(action)
        intent = await self._rollback_record(bound["candidate_id"])
        if intent is not None and intent["status"] == "INTENT_RECORDED":
            expected_after = intent["rollback_payload"].get("expected_after")
            if state == expected_after:
                await self._finalize_record(
                    bound,
                    intent["rollback_payload"].get("before_state", state),
                    state,
                )
                return models.RunStatus.ROLLED_BACK, "ROLLBACK_APPLIED"
        reason = self._safe_reason(bound, state, action)
        if reason is not None:
            await self._record(bound, "ROLLBACK_BLOCKED", {"reason": reason, "state": state})
            return models.RunStatus.ROLLBACK_BLOCKED, reason
        expected_after = _without_owned_index(state, action.index_name)
        await self._record(
            bound,
            "INTENT_RECORDED",
            {"before_state": state, "expected_after": expected_after},
        )
        await self._adapter.drop_index(Namespace(action.collection), action.index_name)
        after = await self._state(action)
        if after != expected_after:
            await self._record(bound, "ROLLBACK_BLOCKED", {"reason": "INVERSE_EFFECT_UNVERIFIED", "state": after})
            return models.RunStatus.ROLLBACK_BLOCKED, "INVERSE_EFFECT_UNVERIFIED"
        await self._finalize_record(bound, state, after)
        return models.RunStatus.ROLLED_BACK, "ROLLBACK_APPLIED"

    async def _finalize_record(
        self, bound: Mapping[str, Any], before: Mapping[str, Any], after: Mapping[str, Any]
    ) -> None:
        action = CreateIndexAction.model_validate(bound["action_payload"])
        inverse = DropIndexAction.model_validate(bound["inverse_action"])
        if not await self._rollback_ledger_exists(bound):
            await self._ledger.append(
                target_id=bound["target_id"], run_id=bound["run_id"], candidate_id=bound["candidate_id"], action_id=str(bound["action_id"]),
                event_type="ROLLBACK_APPLIED", before_state=before, intended_state=after, after_state=after,
                forward_action=inverse.model_dump(mode="json"), inverse_action=action.model_dump(mode="json"),
                evidence_hash=bound["authority_fingerprint"], actor=self._actor,
            )
        await self._record(bound, "ROLLED_BACK", {"before_state": before, "after_state": after})

    async def _rollback_ledger_exists(self, bound: Mapping[str, Any]) -> bool:
        async with self._engine.connect() as connection:
            count = await connection.scalar(
                text(
                    "SELECT count(*) FROM production_ledger_entries "
                    "WHERE run_id=:run_id AND candidate_id=:candidate_id "
                    "AND event_type='ROLLBACK_APPLIED'"
                ),
                {"run_id": bound["run_id"], "candidate_id": bound["candidate_id"]},
            )
        return bool(count)

    async def _bound(self, run_id: UUID) -> Mapping[str, Any]:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    select(
                        models.OptimizationRun.__table__.c.id.label("run_id"), models.OptimizationRun.__table__.c.target_id,
                        models.DeploymentArtifact.__table__.c.candidate_id, models.DeploymentArtifact.__table__.c.candidate_fingerprint,
                        models.DeploymentArtifact.__table__.c.action_fingerprint, models.DeploymentArtifact.__table__.c.before_state,
                        models.DeploymentArtifact.__table__.c.after_state, models.DeploymentArtifact.__table__.c.inverse_action,
                        models.Candidate.__table__.c.deterministic_fingerprint, models.CandidateAction.__table__.c.id.label("action_id"),
                        models.CandidateAction.__table__.c.action_payload, models.AuthorityDecision.__table__.c.integrity_fingerprint.label("authority_fingerprint"),
                    )
                    .select_from(models.OptimizationRun.__table__)
                    .join(models.DeploymentArtifact.__table__, models.DeploymentArtifact.__table__.c.optimization_run_id == models.OptimizationRun.__table__.c.id)
                    .join(models.Candidate.__table__, models.Candidate.__table__.c.id == models.DeploymentArtifact.__table__.c.candidate_id)
                    .join(models.CandidateAction.__table__, models.CandidateAction.__table__.c.candidate_id == models.Candidate.__table__.c.id)
                    .join(models.AuthorityDecision.__table__, models.AuthorityDecision.__table__.c.optimization_run_id == models.OptimizationRun.__table__.c.id)
                    .where(models.OptimizationRun.__table__.c.id == run_id)
                )
            ).mappings().one_or_none()
        if row is None:
            raise ValueError("deployment artifact is required for rollback")
        return cast(Mapping[str, Any], row)

    def _safe_reason(self, bound: Mapping[str, Any], state: Mapping[str, Any], action: CreateIndexAction) -> str | None:
        if bound["candidate_fingerprint"] != bound["deterministic_fingerprint"]:
            return "CANDIDATE_FINGERPRINT_DRIFT"
        if bound["after_state"] is None or _hash_action(action) != bound["action_fingerprint"]:
            return "DEPLOYMENT_ARTIFACT_INVALID"
        if not state["namespace_exists"]:
            return "NAMESPACE_MISMATCH"
        wanted = [[field.field, field.direction] for field in action.fields]
        matching = [item for item in state["indexes"] if item["name"] == action.index_name]
        if len(matching) != 1 or matching[0]["keys"] != wanted:
            return "INDEX_SPEC_MISMATCH"
        # An exact full-state check detects human/external changes since deploy;
        # fail closed rather than make a destructive ownership guess.
        if state != bound["after_state"]:
            return "RELEVANT_DRIFT_DETECTED"
        return None

    async def _record(self, bound: Mapping[str, Any], status: str, payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        async with self._engine.begin() as connection:
            existing = (
                await connection.execute(select(models.RollbackRecord.__table__).where(models.RollbackRecord.__table__.c.candidate_id == bound["candidate_id"]).with_for_update())
            ).mappings().one_or_none()
            if existing is None:
                await connection.execute(insert(models.RollbackRecord.__table__).values(id=uuid4(), created_at=now, updated_at=now, candidate_id=bound["candidate_id"], status=status, rollback_payload=payload))
            elif existing["status"] == "INTENT_RECORDED" and status in {"ROLLED_BACK", "ROLLBACK_BLOCKED"}:
                await connection.execute(
                    models.RollbackRecord.__table__.update()
                    .where(models.RollbackRecord.__table__.c.id == existing["id"])
                    .values(status=status, rollback_payload=payload, updated_at=now)
                )
            elif existing["status"] != status:
                raise ValueError("rollback outcome already recorded")

    async def _recorded_outcome(self, candidate_id: UUID) -> tuple[models.RunStatus, str] | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    select(models.RollbackRecord.__table__.c.status, models.RollbackRecord.__table__.c.rollback_payload)
                    .where(models.RollbackRecord.__table__.c.candidate_id == candidate_id)
                )
            ).mappings().one_or_none()
        if row is None:
            return None
        if row["status"] == "ROLLED_BACK":
            return models.RunStatus.ROLLED_BACK, "ROLLBACK_APPLIED"
        if row["status"] == "ROLLBACK_BLOCKED":
            payload = row["rollback_payload"] or {}
            return models.RunStatus.ROLLBACK_BLOCKED, str(payload.get("reason", "ROLLBACK_BLOCKED"))
        if row["status"] == "INTENT_RECORDED":
            return None
        raise ValueError("invalid persisted rollback status")

    async def _rollback_record(self, candidate_id: UUID) -> Mapping[str, Any] | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    select(models.RollbackRecord.__table__).where(
                        models.RollbackRecord.__table__.c.candidate_id == candidate_id
                    )
                )
            ).mappings().one_or_none()
        return cast(Mapping[str, Any] | None, row)

    async def _state(self, action: CreateIndexAction) -> dict[str, Any]:
        namespace = Namespace(action.collection)
        namespaces = await self._adapter.list_namespaces()
        indexes = await self._adapter.list_indexes(namespace) if namespace in namespaces else ()
        return {"database": action.database, "collection": action.collection, "namespace_exists": namespace in namespaces,
                "indexes": [{"name": item.name, "keys": [list(pair) for pair in item.keys]} for item in indexes]}


def _hash_action(action: CreateIndexAction) -> str:
    return hashlib.sha256(json.dumps(action.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _without_owned_index(state: Mapping[str, Any], index_name: str) -> dict[str, Any]:
    result = dict(state)
    result["indexes"] = [item for item in state["indexes"] if item["name"] != index_name]
    return result
