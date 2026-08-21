"""Fail-closed production executor for admitted typed index actions."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.actions.schemas import CreateIndexAction
from app.adapters.contracts import DatabaseAdapter, IndexSpec, Namespace
from app.admission.models import AdmissionResult, AdmissionStatus
from app.approvals.flow import ApprovalFlow
from app.ledger.chain import AppendOnlyLedger, LedgerEntry


class ProductionExecutionError(RuntimeError):
    """Raised when an action fails a required production safety gate."""


@dataclass(frozen=True)
class DeploymentRequest:
    """All evidence required to deploy one already-admitted typed action."""

    target_id: str
    action_id: str
    action: CreateIndexAction
    admission: AdmissionResult
    evidence_hash: str
    expected_state_hash: str
    actor: str
    semi_autonomous: bool = True


@dataclass(frozen=True)
class DeploymentResult:
    """Ledger evidence for a completed typed production action."""

    prepared_entry: LedgerEntry
    applied_entry: LedgerEntry
    resulting_state_hash: str


class ProductionExecutor:
    """Deploy only admitted typed actions through the constrained adapter contract."""

    def __init__(self, adapter: DatabaseAdapter, approvals: ApprovalFlow, ledger: AppendOnlyLedger) -> None:
        self._adapter = adapter
        self._approvals = approvals
        self._ledger = ledger
        self._target_locks: dict[str, asyncio.Lock] = {}

    async def current_state_hash(self, action: CreateIndexAction) -> str:
        """Hash the exact target namespace and index state used for verification."""
        return _state_hash(await self._current_state(action))

    async def deploy(self, request: DeploymentRequest) -> DeploymentResult:
        """Lock, verify, ledger, execute, verify, ledger, and always unlock one typed action."""
        if not isinstance(request.action, CreateIndexAction):
            raise ProductionExecutionError("raw or unsupported production action rejected")
        if request.admission.status is not AdmissionStatus.ADMITTED or not request.admission.production_eligible:
            raise ProductionExecutionError("only production-eligible admitted actions may deploy")

        lock = self._target_locks.setdefault(request.target_id, asyncio.Lock())
        async with lock:
            if request.semi_autonomous:
                self._approvals.require_current_approval(request.action_id, request.evidence_hash, request.target_id)

            before_state = await self._current_state(request.action)
            if _state_hash(before_state) != request.expected_state_hash:
                raise ProductionExecutionError("current target state differs from verified evidence")
            self._verify_preconditions(before_state, request.action)

            inverse = request.action.inverse()
            intended_state = _intended_state(before_state, request.action)
            prepared = self._ledger.append(
                before_state=before_state,
                intended_state=intended_state,
                after_state=before_state,
                forward_action={
                    "phase": "PREPARED",
                    "target_id": request.target_id,
                    "index_fingerprint": _index_fingerprint(request.action),
                    **request.action.model_dump(mode="json"),
                },
                inverse_action=inverse.model_dump(mode="json"),
                evidence_hash=request.evidence_hash,
                actor=request.actor,
            )

            namespace = Namespace(collection=request.action.collection)
            index = IndexSpec(
                name=request.action.index_name,
                keys=tuple((field.field, field.direction) for field in request.action.fields),
            )
            await self._adapter.create_index(namespace, index)
            after_state = await self._current_state(request.action)
            self._verify_applied(after_state, request.action)
            applied = self._ledger.append(
                before_state=before_state,
                intended_state=intended_state,
                after_state=after_state,
                forward_action={
                    "phase": "APPLIED",
                    "target_id": request.target_id,
                    "index_fingerprint": _index_fingerprint(request.action),
                    **request.action.model_dump(mode="json"),
                },
                inverse_action=inverse.model_dump(mode="json"),
                evidence_hash=request.evidence_hash,
                actor=request.actor,
            )
            return DeploymentResult(prepared, applied, _state_hash(after_state))

    async def _current_state(self, action: CreateIndexAction) -> dict[str, Any]:
        namespace = Namespace(collection=action.collection)
        namespaces = await self._adapter.list_namespaces()
        indexes = await self._adapter.list_indexes(namespace) if namespace in namespaces else ()
        return {
            "database": action.database,
            "collection": action.collection,
            "namespace_exists": namespace in namespaces,
            "indexes": [{"name": index.name, "keys": list(index.keys)} for index in indexes],
        }

    @staticmethod
    def _verify_preconditions(state: dict[str, Any], action: CreateIndexAction) -> None:
        if not state["namespace_exists"]:
            raise ProductionExecutionError("target namespace is absent")
        if any(index["name"] == action.index_name for index in state["indexes"]):
            raise ProductionExecutionError("target index already exists")

    @staticmethod
    def _verify_applied(state: dict[str, Any], action: CreateIndexAction) -> None:
        expected_keys = [(field.field, field.direction) for field in action.fields]
        matching = [index for index in state["indexes"] if index["name"] == action.index_name]
        if len(matching) != 1 or matching[0]["keys"] != expected_keys:
            raise ProductionExecutionError("resulting target state does not match typed action")


def _intended_state(before_state: dict[str, Any], action: CreateIndexAction) -> dict[str, Any]:
    """Build the state expected after exactly one typed index creation."""
    return {
        **before_state,
        "indexes": [
            *before_state["indexes"],
            {"name": action.index_name, "keys": [(field.field, field.direction) for field in action.fields]},
        ],
    }


def _state_hash(state: dict[str, Any]) -> str:
    """Return a canonical SHA-256 fingerprint for current-state verification."""
    serialized = json.dumps(state, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _index_fingerprint(action: CreateIndexAction) -> str:
    """Fingerprint the exact safe index specification the ledger owns."""
    payload = {"name": action.index_name, "keys": [(field.field, field.direction) for field in action.fields]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
