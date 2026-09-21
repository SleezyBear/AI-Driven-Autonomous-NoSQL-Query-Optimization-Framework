"""Durable, run-bound deployment of the one admitted typed production action.

This module deliberately composes the existing restricted adapter, PostgreSQL
target lock, recovery checkpoint, and append-only ledger.  It never accepts a
command string and it never writes application documents.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping, cast
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.actions.schemas import CreateIndexAction
from app.adapters.contracts import DatabaseAdapter, IndexSpec, Namespace
from app.autonomy.readiness import (
    AUTO_ELIGIBLE_ACTIONS,
    authority_integrity_fingerprint,
    environment_binding,
)
from app.db import models
from app.ledger.postgres import PostgresProductionLedger
from app.production.target_lock import PostgresTargetMutationLock
from app.recovery.durable import DurableRecovery
from app.worker.durable import ExecutionContext


class DurableDeploymentError(RuntimeError):
    """A fail-closed production deployment invariant was not met."""


class DurableDeploymentService:
    """Deploy/reconcile exactly one authority-bound CREATE_INDEX action."""

    def __init__(self, engine: AsyncEngine, adapter: DatabaseAdapter, *, actor: str = "durable-production-worker") -> None:
        self._engine = engine
        self._adapter = adapter
        self._actor = actor
        self._locks = PostgresTargetMutationLock(engine)
        self._ledger = PostgresProductionLedger(engine)
        self._recovery = DurableRecovery(engine)

    async def deploy_for_run(self, run_id: UUID, context: ExecutionContext) -> Mapping[str, Any]:
        """Reconcile a deployment without duplicating its external mutation."""
        context.ensure_lease_owned()
        bound = await self._load_bound_action(run_id)
        lease = await self._locks.try_acquire(bound["target_id"])
        if lease is None:
            raise DurableDeploymentError("TARGET_LOCK_UNAVAILABLE")
        try:
            context.ensure_lease_owned()
            return await self._deploy_locked(bound, context)
        finally:
            await lease.release()

    async def _deploy_locked(self, bound: Mapping[str, Any], context: ExecutionContext) -> Mapping[str, Any]:
        action = CreateIndexAction.model_validate(bound["action_payload"])
        before = await self._state(action)
        fingerprint = _action_fingerprint(action)
        artifact, intent_created = await self._intent(bound, before, action, fingerprint)
        # An already applied effect is reconciled below; never call create_index
        # a second time merely because the process disappeared after MongoDB did
        # the work.
        if _value(bound["run_status"]) == models.RunStatus.APPROVED.value:
            await self._transition(bound["run_id"], models.RunStatus.DEPLOYING)
        elif _value(bound["run_status"]) not in {models.RunStatus.DEPLOYING.value, models.RunStatus.DEPLOYED.value}:
            raise DurableDeploymentError("RUN_NOT_APPROVED_FOR_DEPLOYMENT")

        # Once the external result and durable artifact are both present, a
        # recovered job only verifies the exact state.  It never adds another
        # ledger claim or repeats an already-authoritative mutation.
        if artifact["status"] == "APPLIED":
            if not _has_exact_index(before, action):
                raise DurableDeploymentError("DEPLOYED_EXTERNAL_STATE_DRIFT")
            current = await self._run_status(bound["run_id"])
            if current is models.RunStatus.DEPLOYING:
                await self._transition(bound["run_id"], models.RunStatus.DEPLOYED)
            elif current is not models.RunStatus.DEPLOYED:
                raise DurableDeploymentError("RUN_NOT_DEPLOYING_FOR_RECOVERY")
            return artifact

        await self._recovery.record_intent(
            idempotency_key=artifact["idempotency_key"],
            action_id=str(bound["action_id"]),
            target_id=bound["target_id"],
            expected_fingerprint=fingerprint,
        )
        if intent_created:
            await self._append_intent(bound, before, action)
        context.ensure_lease_owned()

        async def exact_effect(expected: str) -> bool:
            state = await self._state(action)
            return expected == fingerprint and _has_exact_index(state, action)

        async def mutation() -> None:
            context.ensure_lease_owned()
            await self._adapter.create_index(
                Namespace(action.collection),
                IndexSpec(action.index_name, tuple((field.field, field.direction) for field in action.fields)),
            )

        await self._recovery.execute_or_recover(
            idempotency_key=artifact["idempotency_key"], target_has_exact_effect=exact_effect, apply_mutation=mutation
        )
        context.ensure_lease_owned()
        after = await self._state(action)
        if not _has_exact_index(after, action):
            raise DurableDeploymentError("EXTERNAL_EFFECT_VERIFICATION_FAILED")
        persisted = await self._mark_applied(artifact["id"], after)
        await self._append_applied(bound, before, after, action)
        context.ensure_lease_owned()
        current = await self._run_status(bound["run_id"])
        if current is models.RunStatus.DEPLOYING:
            await self._transition(bound["run_id"], models.RunStatus.DEPLOYED)
        return persisted

    async def _load_bound_action(self, run_id: UUID) -> Mapping[str, Any]:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    select(
                        models.OptimizationRun.__table__.c.id.label("run_id"),
                        models.OptimizationRun.__table__.c.target_id,
                        models.OptimizationRun.__table__.c.status.label("run_status"),
                        models.OptimizationRun.__table__.c.deployment_mode.label("run_deployment_mode"),
                        models.AdmissionArtifact.__table__.c.selected_candidate_id,
                        models.AdmissionArtifact.__table__.c.production_eligible.label("admission_production_eligible"),
                        models.AuthorityDecision.__table__.c.candidate_id.label("authority_candidate_id"),
                        models.AuthorityDecision.__table__.c.authority_type,
                        models.AuthorityDecision.__table__.c.authority_reason,
                        models.AuthorityDecision.__table__.c.deployment_mode.label("authority_deployment_mode"),
                        models.AuthorityDecision.__table__.c.production_autonomy_eligible,
                        models.AuthorityDecision.__table__.c.candidate_fingerprint,
                        models.AuthorityDecision.__table__.c.integrity_fingerprint,
                        models.Candidate.__table__.c.deterministic_fingerprint,
                        models.Candidate.__table__.c.status.label("candidate_status"),
                        models.Candidate.__table__.c.policy_classification,
                        models.WorkloadSnapshot.__table__.c.completeness,
                        models.Target.__table__.c.connection_label,
                        models.Target.__table__.c.deployment_mode.label("target_deployment_mode"),
                        models.Target.__table__.c.state.label("target_state"),
                        models.Target.__table__.c.is_active.label("target_is_active"),
                        models.CandidateAction.__table__.c.id.label("action_id"),
                        models.CandidateAction.__table__.c.action_type,
                        models.CandidateAction.__table__.c.action_payload,
                    )
                    .select_from(models.OptimizationRun.__table__)
                    .join(models.AdmissionArtifact.__table__, models.AdmissionArtifact.__table__.c.optimization_run_id == models.OptimizationRun.__table__.c.id)
                    .join(models.AuthorityDecision.__table__, models.AuthorityDecision.__table__.c.optimization_run_id == models.OptimizationRun.__table__.c.id)
                    .join(models.Candidate.__table__, models.Candidate.__table__.c.id == models.AdmissionArtifact.__table__.c.selected_candidate_id)
                    .join(models.CandidateAction.__table__, models.CandidateAction.__table__.c.candidate_id == models.Candidate.__table__.c.id)
                    .join(models.WorkloadSnapshot.__table__, models.WorkloadSnapshot.__table__.c.id == models.OptimizationRun.__table__.c.workload_snapshot_id)
                    .join(models.Target.__table__, models.Target.__table__.c.id == models.OptimizationRun.__table__.c.target_id)
                    .where(models.OptimizationRun.__table__.c.id == run_id)
                )
            ).mappings().one_or_none()
        if row is None or row["selected_candidate_id"] != row["authority_candidate_id"]:
            raise DurableDeploymentError("AUTHORITY_BINDING_MISSING")
        if row["deterministic_fingerprint"] != row["candidate_fingerprint"]:
            raise DurableDeploymentError("CANDIDATE_FINGERPRINT_DRIFT")
        if row["action_type"] != "CREATE_INDEX" or row["action_type"] not in AUTO_ELIGIBLE_ACTIONS:
            raise DurableDeploymentError("UNSUPPORTED_TYPED_PRODUCTION_ACTION")
        if _value(row["candidate_status"]) != models.CandidateStatus.ADMITTED.value:
            raise DurableDeploymentError("CANDIDATE_NOT_ADMITTED")
        if row["run_deployment_mode"] != row["authority_deployment_mode"]:
            raise DurableDeploymentError("DEPLOYMENT_MODE_DRIFT")
        capability, credential = await self._environment_evidence(row["target_id"])
        target_identity, capability_fingerprint, security_fingerprint = environment_binding(
            {
                "id": row["target_id"],
                "connection_label": row["connection_label"],
                "deployment_mode": row["target_deployment_mode"],
                "state": row["target_state"],
                "is_active": row["target_is_active"],
            },
            capability,
            credential,
        )
        expected_authority_fingerprint = authority_integrity_fingerprint(
            run_id,
            row["authority_candidate_id"],
            row["candidate_fingerprint"],
            row["authority_deployment_mode"],
            row["authority_type"],
            row["authority_reason"],
            bool(row["production_autonomy_eligible"]),
            bool(row["admission_production_eligible"]),
            target_identity,
            capability_fingerprint,
            security_fingerprint,
        )
        if expected_authority_fingerprint != row["integrity_fingerprint"]:
            raise DurableDeploymentError("PREDEPLOYMENT_EVIDENCE_DRIFT")
        if row["authority_type"] == "AUTONOMOUS" and not (
            row["run_deployment_mode"] == "FULL_AUTONOMOUS"
            and row["production_autonomy_eligible"]
            and row["admission_production_eligible"]
            and row["policy_classification"] == "AUTO_ELIGIBLE_AFTER_ADMISSION"
        ):
            raise DurableDeploymentError("AUTONOMY_PREREQUISITE_DRIFT")
        if row["authority_type"] == "HUMAN_REQUIRED":
            async with self._engine.connect() as connection:
                approval = (
                    await connection.execute(
                        select(models.ApprovalRequest.__table__.c.id).where(
                            models.ApprovalRequest.__table__.c.optimization_run_id == run_id,
                            models.ApprovalRequest.__table__.c.candidate_id == row["selected_candidate_id"],
                            models.ApprovalRequest.__table__.c.candidate_fingerprint == row["candidate_fingerprint"],
                            models.ApprovalRequest.__table__.c.status == "APPROVED",
                            models.ApprovalRequest.__table__.c.expires_at > datetime.now(timezone.utc),
                        )
                    )
                ).scalar_one_or_none()
            if approval is None:
                raise DurableDeploymentError("CURRENT_APPROVAL_REQUIRED")
        return cast(Mapping[str, Any], row)

    async def _environment_evidence(
        self, target_id: UUID
    ) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
        async with self._engine.connect() as connection:
            capability = (
                await connection.execute(
                    select(models.CapabilitySnapshot.__table__)
                    .where(models.CapabilitySnapshot.__table__.c.target_id == target_id)
                    .order_by(models.CapabilitySnapshot.__table__.c.created_at.desc())
                    .limit(1)
                )
            ).mappings().one_or_none()
            credential = (
                await connection.execute(
                    select(models.TargetCredential.__table__).where(
                        models.TargetCredential.__table__.c.target_id == target_id
                    )
                )
            ).mappings().one_or_none()
        return capability, credential

    async def _intent(
        self, bound: Mapping[str, Any], before: dict[str, Any], action: CreateIndexAction, fingerprint: str
    ) -> tuple[Mapping[str, Any], bool]:
        key = _idempotency_key(bound["run_id"], bound["candidate_fingerprint"], fingerprint)
        inverse = action.inverse().model_dump(mode="json")
        now = datetime.now(timezone.utc)
        async with self._engine.begin() as connection:
            existing = (
                await connection.execute(
                    select(models.DeploymentArtifact.__table__).where(models.DeploymentArtifact.__table__.c.optimization_run_id == bound["run_id"]).with_for_update()
                )
            ).mappings().one_or_none()
            if existing is not None:
                if (
                    existing["candidate_id"] != bound["selected_candidate_id"]
                    or existing["candidate_fingerprint"] != bound["candidate_fingerprint"]
                    or existing["action_fingerprint"] != fingerprint
                ):
                    raise DurableDeploymentError("DEPLOYMENT_ARTIFACT_BINDING_DRIFT")
                return cast(Mapping[str, Any], existing), False
            result = await connection.execute(
                insert(models.DeploymentArtifact.__table__)
                .values(
                    id=uuid4(), created_at=now, updated_at=now,
                    optimization_run_id=bound["run_id"], candidate_id=bound["selected_candidate_id"],
                    candidate_fingerprint=bound["candidate_fingerprint"], action_fingerprint=fingerprint,
                    idempotency_key=key, status="INTENT_RECORDED", before_state=before,
                    inverse_action=inverse, after_state=None,
                )
                .returning(*models.DeploymentArtifact.__table__.c)
            )
            return cast(Mapping[str, Any], result.mappings().one()), True

    async def _mark_applied(self, artifact_id: UUID, after: dict[str, Any]) -> Mapping[str, Any]:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(models.DeploymentArtifact.__table__)
                .where(models.DeploymentArtifact.__table__.c.id == artifact_id)
                .values(status="APPLIED", after_state=after, updated_at=datetime.now(timezone.utc))
                .returning(*models.DeploymentArtifact.__table__.c)
            )
            return cast(Mapping[str, Any], result.mappings().one())

    async def _append_intent(self, bound: Mapping[str, Any], before: dict[str, Any], action: CreateIndexAction) -> None:
        # The ledger is append-only. Multiple recovery passes can produce intent
        # evidence, but only the one idempotency key can produce one external effect.
        await self._ledger.append(
            target_id=bound["target_id"], run_id=bound["run_id"], candidate_id=bound["selected_candidate_id"], action_id=str(bound["action_id"]),
            event_type="DEPLOYMENT_INTENT", before_state=before, intended_state=_intended(before, action), after_state=before,
            forward_action=action.model_dump(mode="json"), inverse_action=action.inverse().model_dump(mode="json"),
            evidence_hash=bound["integrity_fingerprint"], actor=self._actor,
        )

    async def _append_applied(self, bound: Mapping[str, Any], before: dict[str, Any], after: dict[str, Any], action: CreateIndexAction) -> None:
        await self._ledger.append(
            target_id=bound["target_id"], run_id=bound["run_id"], candidate_id=bound["selected_candidate_id"], action_id=str(bound["action_id"]),
            event_type="DEPLOYMENT_APPLIED", before_state=before, intended_state=_intended(before, action), after_state=after,
            forward_action=action.model_dump(mode="json"), inverse_action=action.inverse().model_dump(mode="json"),
            evidence_hash=bound["integrity_fingerprint"], actor=self._actor,
        )

    async def _state(self, action: CreateIndexAction) -> dict[str, Any]:
        namespace = Namespace(action.collection)
        namespaces = await self._adapter.list_namespaces()
        indexes = await self._adapter.list_indexes(namespace) if namespace in namespaces else ()
        return {"database": action.database, "collection": action.collection, "namespace_exists": namespace in namespaces,
                "indexes": [{"name": item.name, "keys": [list(pair) for pair in item.keys]} for item in indexes]}

    async def _run_status(self, run_id: UUID) -> models.RunStatus:
        async with self._engine.connect() as connection:
            status = await connection.scalar(select(models.OptimizationRun.__table__.c.status).where(models.OptimizationRun.__table__.c.id == run_id))
        if status is None:
            raise DurableDeploymentError("RUN_NOT_FOUND")
        return models.RunStatus(_value(status))

    async def _transition(self, run_id: UUID, target: models.RunStatus) -> None:
        from app.db.repositories import RunRepository
        await RunRepository(self._engine).transition(run_id, target)


def _value(value: object) -> str:
    return str(value.value if hasattr(value, "value") else value)


def _action_fingerprint(action: CreateIndexAction) -> str:
    return hashlib.sha256(json.dumps(action.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _idempotency_key(run_id: UUID, candidate_fingerprint: str, action_fingerprint: str) -> str:
    return hashlib.sha256(f"{run_id}:{candidate_fingerprint}:{action_fingerprint}".encode()).hexdigest()


def _has_exact_index(state: Mapping[str, Any], action: CreateIndexAction) -> bool:
    wanted = [[field.field, field.direction] for field in action.fields]
    return bool(sum(item["name"] == action.index_name and item["keys"] == wanted for item in state["indexes"]) == 1)


def _intended(before: Mapping[str, Any], action: CreateIndexAction) -> dict[str, Any]:
    return {**before, "indexes": [*before["indexes"], {"name": action.index_name, "keys": [[field.field, field.direction] for field in action.fields]}]}
