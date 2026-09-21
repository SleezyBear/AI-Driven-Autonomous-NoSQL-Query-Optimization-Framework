"""Durable typed deployment and exact rollback of optimizer-owned query hints."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping, cast
from uuid import UUID, uuid4

from sqlalchemy import insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.actions.schemas import SetQuerySettingsIndexHintAction
from app.adapters.contracts import DatabaseAdapter, Namespace, QuerySettingsIndexHint
from app.db import models
from app.ledger.postgres import PostgresProductionLedger
from app.production.target_lock import PostgresTargetMutationLock


class DurableQuerySettingsError(RuntimeError):
    """The exact owned query-setting transition cannot be proved safe."""


class DurableQuerySettingsDeploymentService:
    """Persist intent before a typed setting mutation and reconcile every retry."""

    def __init__(self, engine: AsyncEngine, adapter: DatabaseAdapter) -> None:
        self._engine = engine
        self._adapter = adapter
        self._locks = PostgresTargetMutationLock(engine)
        self._ledger = PostgresProductionLedger(engine)

    async def deploy(
        self,
        *,
        target_id: UUID,
        action: SetQuerySettingsIndexHintAction,
        evidence_hash: str,
        optimization_run_id: UUID | None = None,
    ) -> Mapping[str, Any]:
        lease = await self._locks.try_acquire(target_id)
        if lease is None:
            raise DurableQuerySettingsError("TARGET_LOCK_UNAVAILABLE")
        try:
            return await self._deploy_locked(
                target_id, action, evidence_hash, optimization_run_id
            )
        finally:
            await lease.release()

    async def _deploy_locked(
        self,
        target_id: UUID,
        action: SetQuerySettingsIndexHintAction,
        evidence_hash: str,
        optimization_run_id: UUID | None,
    ) -> Mapping[str, Any]:
        index_names = {
            item.name
            for item in await self._adapter.list_indexes(Namespace(action.collection))
        }
        if not set(action.allowed_indexes).issubset(index_names):
            raise DurableQuerySettingsError("ALLOWED_INDEX_NOT_PRESENT")
        fingerprint = _hash(action.model_dump(mode="json"))
        key = _hash({"target": target_id, "action": fingerprint, "evidence": evidence_hash})
        ownership = _hash({"target": target_id, "shape": action.query_shape_hash, "action": fingerprint})
        current = await self._adapter.get_query_settings_index_hint(
            Namespace(action.collection), action.query_shape_hash
        )
        existing = await self._by_key(key)
        intended = QuerySettingsIndexHint(action.allowed_indexes)
        if existing is not None:
            if existing["action_fingerprint"] != fingerprint:
                raise DurableQuerySettingsError("ACTION_FINGERPRINT_DRIFT")
            if existing["status"] == "APPLIED":
                if current != intended:
                    raise DurableQuerySettingsError("QUERY_SETTINGS_AFTER_STATE_DRIFT")
                await self._append_once(
                    existing,
                    event_type="QUERY_SETTINGS_APPLIED",
                    before=existing["before_state"],
                    intended=existing["intended_state"],
                    after=_state(action, current),
                    forward=action.model_dump(mode="json"),
                    inverse=action.inverse().model_dump(mode="json"),
                    evidence_hash=evidence_hash,
                )
                return existing
            if existing["status"] == "INTENT_RECORDED" and current == intended:
                applied = await self._mark(
                    existing["id"], "APPLIED", _state(action, current)
                )
                await self._append_once(
                    applied,
                    event_type="QUERY_SETTINGS_APPLIED",
                    before=applied["before_state"],
                    intended=applied["intended_state"],
                    after=_state(action, current),
                    forward=action.model_dump(mode="json"),
                    inverse=action.inverse().model_dump(mode="json"),
                    evidence_hash=evidence_hash,
                )
                return applied
        elif current is not None:
            # No optimizer ownership evidence exists, therefore the setting is
            # human/external and cannot be modified autonomously.
            raise DurableQuerySettingsError("HUMAN_QUERY_SETTINGS_PRESENT")
        before = _state(action, current)
        intended_state = _state(action, intended)
        row = existing or await self._intent(
            target_id,
            optimization_run_id,
            action,
            fingerprint,
            key,
            ownership,
            before,
            intended_state,
        )
        await self._adapter.set_query_settings_index_hint(
            Namespace(action.collection), action.query_shape_hash, intended
        )
        observed = await self._adapter.get_query_settings_index_hint(
            Namespace(action.collection), action.query_shape_hash
        )
        if observed != intended:
            raise DurableQuerySettingsError("QUERY_SETTINGS_EFFECT_UNVERIFIED")
        applied = await self._mark(row["id"], "APPLIED", _state(action, observed))
        await self._append_once(
            applied,
            event_type="QUERY_SETTINGS_APPLIED",
            before=before,
            intended=intended_state,
            after=_state(action, observed),
            forward=action.model_dump(mode="json"),
            inverse=action.inverse().model_dump(mode="json"),
            evidence_hash=evidence_hash,
        )
        return applied

    async def rollback(self, deployment_id: UUID, *, evidence_hash: str) -> Mapping[str, Any]:
        deployment = await self._by_id(deployment_id)
        if deployment is None or deployment["status"] not in {
            "APPLIED",
            "ROLLBACK_INTENT",
            "ROLLED_BACK",
        }:
            raise DurableQuerySettingsError("OWNED_APPLIED_SETTING_REQUIRED")
        action = SetQuerySettingsIndexHintAction.model_validate(
            {
                "action_type": "SET_QUERY_SETTINGS_INDEX_HINT",
                "database": deployment["before_state"]["database"],
                "collection": deployment["before_state"]["collection"],
                "query_shape_hash": deployment["query_shape_hash"],
                "allowed_indexes": tuple(deployment["intended_state"]["allowed_indexes"]),
                "previous_allowed_indexes": deployment["before_state"]["allowed_indexes"],
            }
        )
        lease = await self._locks.try_acquire(deployment["target_id"])
        if lease is None:
            raise DurableQuerySettingsError("TARGET_LOCK_UNAVAILABLE")
        try:
            current = await self._adapter.get_query_settings_index_hint(
                Namespace(action.collection), action.query_shape_hash
            )
            intended = QuerySettingsIndexHint(action.allowed_indexes)
            previous = (
                None
                if action.previous_allowed_indexes is None
                else QuerySettingsIndexHint(action.previous_allowed_indexes)
            )
            if deployment["status"] == "ROLLED_BACK":
                if current != previous:
                    raise DurableQuerySettingsError("QUERY_SETTINGS_ROLLBACK_DRIFT")
                await self._append_once(
                    deployment,
                    event_type="QUERY_SETTINGS_ROLLED_BACK",
                    before=deployment["intended_state"],
                    intended=deployment["before_state"],
                    after=_state(action, current),
                    forward=action.inverse().model_dump(mode="json"),
                    inverse=action.model_dump(mode="json"),
                    evidence_hash=evidence_hash,
                )
                return deployment
            if current == previous and deployment["status"] == "ROLLBACK_INTENT":
                rolled_back = await self._mark(
                    deployment_id, "ROLLED_BACK", _state(action, current)
                )
                await self._append_once(
                    rolled_back,
                    event_type="QUERY_SETTINGS_ROLLED_BACK",
                    before=deployment["intended_state"],
                    intended=deployment["before_state"],
                    after=_state(action, current),
                    forward=action.inverse().model_dump(mode="json"),
                    inverse=action.model_dump(mode="json"),
                    evidence_hash=evidence_hash,
                )
                return rolled_back
            if current != intended:
                raise DurableQuerySettingsError("QUERY_SETTINGS_OWNERSHIP_DRIFT")
            await self._mark(deployment_id, "ROLLBACK_INTENT", _state(action, current))
            await self._adapter.set_query_settings_index_hint(
                Namespace(action.collection), action.query_shape_hash, previous
            )
            observed = await self._adapter.get_query_settings_index_hint(
                Namespace(action.collection), action.query_shape_hash
            )
            if observed != previous:
                raise DurableQuerySettingsError("QUERY_SETTINGS_INVERSE_UNVERIFIED")
            rolled_back = await self._mark(
                deployment_id, "ROLLED_BACK", _state(action, observed)
            )
            await self._append_once(
                rolled_back,
                event_type="QUERY_SETTINGS_ROLLED_BACK",
                before=deployment["intended_state"],
                intended=deployment["before_state"],
                after=_state(action, observed),
                forward=action.inverse().model_dump(mode="json"),
                inverse=action.model_dump(mode="json"),
                evidence_hash=evidence_hash,
            )
            return rolled_back
        finally:
            await lease.release()

    async def _intent(
        self,
        target_id: UUID,
        run_id: UUID | None,
        action: SetQuerySettingsIndexHintAction,
        fingerprint: str,
        key: str,
        ownership: str,
        before: Mapping[str, Any],
        intended: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        now = datetime.now(timezone.utc)
        async with self._engine.begin() as connection:
            result = await connection.execute(
                insert(models.QuerySettingsDeployment.__table__)
                .values(
                    id=uuid4(),
                    created_at=now,
                    updated_at=now,
                    target_id=target_id,
                    optimization_run_id=run_id,
                    query_shape_hash=action.query_shape_hash,
                    namespace=f"{action.database}.{action.collection}",
                    action_fingerprint=fingerprint,
                    idempotency_key=key,
                    status="INTENT_RECORDED",
                    before_state=dict(before),
                    intended_state=dict(intended),
                    after_state=None,
                    inverse_action=action.inverse().model_dump(mode="json"),
                    ownership_token=ownership,
                )
                .returning(*models.QuerySettingsDeployment.__table__.c)
            )
            return cast(Mapping[str, Any], result.mappings().one())

    async def _mark(
        self, deployment_id: UUID, status: str, after: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(models.QuerySettingsDeployment.__table__)
                .where(models.QuerySettingsDeployment.__table__.c.id == deployment_id)
                .values(status=status, after_state=dict(after), updated_at=datetime.now(timezone.utc))
                .returning(*models.QuerySettingsDeployment.__table__.c)
            )
            return cast(Mapping[str, Any], result.mappings().one())

    async def _by_key(self, key: str) -> Mapping[str, Any] | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    select(models.QuerySettingsDeployment.__table__).where(
                        models.QuerySettingsDeployment.__table__.c.idempotency_key == key
                    )
                )
            ).mappings().one_or_none()
        return cast(Mapping[str, Any] | None, row)

    async def _append_once(
        self,
        deployment: Mapping[str, Any],
        *,
        event_type: str,
        before: Mapping[str, Any],
        intended: Mapping[str, Any],
        after: Mapping[str, Any],
        forward: Mapping[str, Any],
        inverse: Mapping[str, Any],
        evidence_hash: str,
    ) -> None:
        async with self._engine.connect() as connection:
            exists = await connection.scalar(
                text(
                    "SELECT entry_id FROM production_ledger_entries "
                    "WHERE target_id=:target_id AND action_id=:action_id "
                    "AND event_type=:event_type LIMIT 1"
                )
                .bindparams(
                    target_id=deployment["target_id"],
                    action_id=str(deployment["id"]),
                    event_type=event_type,
                )
            )
        if exists is not None:
            return
        await self._ledger.append(
            target_id=deployment["target_id"],
            run_id=deployment["optimization_run_id"],
            candidate_id=None,
            action_id=str(deployment["id"]),
            event_type=event_type,
            before_state=before,
            intended_state=intended,
            after_state=after,
            forward_action=forward,
            inverse_action=inverse,
            evidence_hash=evidence_hash,
            actor="durable-query-settings-worker",
        )

    async def _by_id(self, deployment_id: UUID) -> Mapping[str, Any] | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    select(models.QuerySettingsDeployment.__table__).where(
                        models.QuerySettingsDeployment.__table__.c.id == deployment_id
                    )
                )
            ).mappings().one_or_none()
        return cast(Mapping[str, Any] | None, row)


def _state(
    action: SetQuerySettingsIndexHintAction, hint: QuerySettingsIndexHint | None
) -> dict[str, Any]:
    return {
        "database": action.database,
        "collection": action.collection,
        "query_shape_hash": action.query_shape_hash,
        "allowed_indexes": None if hint is None else list(hint.allowed_indexes),
    }


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
