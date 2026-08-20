"""Human-gated, allowedIndexes-only production query-settings executor."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass

from app.actions.schemas import SetQuerySettingsIndexHintAction
from app.adapters.contracts import DatabaseAdapter, Namespace, QuerySettingsIndexHint
from app.approvals.flow import ApprovalFlow
from app.ledger.chain import AppendOnlyLedger, LedgerEntry
from app.production.executor import ProductionExecutionError


@dataclass(frozen=True)
class QuerySettingsDeploymentRequest:
    """Evidence and human-approval context for one query-settings update."""

    target_id: str
    action_id: str
    action: SetQuerySettingsIndexHintAction
    evidence_hash: str
    expected_state_hash: str
    actor: str
    semi_autonomous: bool = True


@dataclass(frozen=True)
class QuerySettingsDeploymentResult:
    """Append-only evidence for a query-settings change."""

    prepared_entry: LedgerEntry
    applied_entry: LedgerEntry
    resulting_state_hash: str


@dataclass(frozen=True)
class QuerySettingsRollbackRequest:
    """Identify one applied optimizer-owned query-settings action."""

    target_id: str
    applied_ledger_entry_id: str
    actor: str


class QuerySettingsExecutor:
    """Deploy only allowedIndexes, never reject or queryFramework settings."""

    def __init__(self, adapter: DatabaseAdapter, approvals: ApprovalFlow, ledger: AppendOnlyLedger) -> None:
        self._adapter = adapter
        self._approvals = approvals
        self._ledger = ledger
        self._target_locks: dict[str, asyncio.Lock] = {}

    async def current_state_hash(self, action: SetQuerySettingsIndexHintAction) -> str:
        return _state_hash(action, await self._current_hint(action))

    async def deploy(self, request: QuerySettingsDeploymentRequest) -> QuerySettingsDeploymentResult:
        if not isinstance(request.action, SetQuerySettingsIndexHintAction):
            raise ProductionExecutionError("raw or unsupported query-settings action rejected")
        lock = self._target_locks.setdefault(request.target_id, asyncio.Lock())
        async with lock:
            before = await self._current_hint(request.action)
            if _state_hash(request.action, before) != request.expected_state_hash:
                raise ProductionExecutionError("current query-settings state differs from verified evidence")
            if _allowed_indexes(before) != request.action.previous_allowed_indexes:
                raise ProductionExecutionError("prior query-settings state differs from typed inverse evidence")
            if before is not None or request.semi_autonomous:
                self._approvals.require_current_approval(request.action_id, request.evidence_hash)
            await self._verify_indexes_exist(request.action)

            after = QuerySettingsIndexHint(request.action.allowed_indexes)
            prepared = self._append("PREPARED", request, before, before)
            await self._adapter.set_query_settings_index_hint(
                Namespace(request.action.collection), request.action.query_shape_hash, after
            )
            actual = await self._current_hint(request.action)
            if actual != after:
                raise ProductionExecutionError("resulting query-settings state does not match typed action")
            applied = self._append("APPLIED", request, before, actual)
            return QuerySettingsDeploymentResult(prepared, applied, _state_hash(request.action, actual))

    async def rollback(self, request: QuerySettingsRollbackRequest) -> LedgerEntry:
        entry = next((item for item in self._ledger.entries if item.entry_id == request.applied_ledger_entry_id), None)
        if entry is None or entry.forward_action.get("phase") != "APPLIED":
            raise ProductionExecutionError("ledger-owned applied query-settings action required")
        action = SetQuerySettingsIndexHintAction.model_validate(
            {key: value for key, value in entry.forward_action.items() if key not in {"phase", "target_id"}}
        )
        if entry.forward_action.get("target_id") != request.target_id:
            raise ProductionExecutionError("query-settings rollback target mismatch")
        lock = self._target_locks.setdefault(request.target_id, asyncio.Lock())
        async with lock:
            current = await self._current_hint(action)
            if _allowed_indexes(current) != action.allowed_indexes:
                raise ProductionExecutionError("query-settings drift blocks exact rollback")
            restored = (
                QuerySettingsIndexHint(action.previous_allowed_indexes)
                if action.previous_allowed_indexes is not None
                else None
            )
            await self._adapter.set_query_settings_index_hint(
                Namespace(action.collection), action.query_shape_hash, restored
            )
            if await self._current_hint(action) != restored:
                raise ProductionExecutionError("query-settings rollback did not restore prior state")
            return self._ledger.append(
                before_state=_state(action, current),
                intended_state=_state(action, restored),
                after_state=_state(action, restored),
                forward_action={"phase": "ROLLED_BACK", **action.inverse().model_dump(mode="json")},
                inverse_action=action.model_dump(mode="json"),
                evidence_hash=entry.evidence_hash,
                actor=request.actor,
            )

    async def _current_hint(self, action: SetQuerySettingsIndexHintAction) -> QuerySettingsIndexHint | None:
        return await self._adapter.get_query_settings_index_hint(
            Namespace(action.collection), action.query_shape_hash
        )

    async def _verify_indexes_exist(self, action: SetQuerySettingsIndexHintAction) -> None:
        names = {index.name for index in await self._adapter.list_indexes(Namespace(action.collection))}
        if not set(action.allowed_indexes).issubset(names):
            raise ProductionExecutionError("allowedIndexes must name existing indexes")

    def _append(
        self,
        phase: str,
        request: QuerySettingsDeploymentRequest,
        before: QuerySettingsIndexHint | None,
        after: QuerySettingsIndexHint | None,
    ) -> LedgerEntry:
        return self._ledger.append(
            before_state=_state(request.action, before),
            intended_state=_state(request.action, QuerySettingsIndexHint(request.action.allowed_indexes)),
            after_state=_state(request.action, after),
            forward_action={"phase": phase, "target_id": request.target_id, **request.action.model_dump(mode="json")},
            inverse_action=request.action.inverse().model_dump(mode="json"),
            evidence_hash=request.evidence_hash,
            actor=request.actor,
        )


def _allowed_indexes(hint: QuerySettingsIndexHint | None) -> tuple[str, ...] | None:
    return hint.allowed_indexes if hint is not None else None


def _state(action: SetQuerySettingsIndexHintAction, hint: QuerySettingsIndexHint | None) -> dict[str, object]:
    return {"database": action.database, "collection": action.collection, "query_shape_hash": action.query_shape_hash, "allowed_indexes": _allowed_indexes(hint)}


def _state_hash(action: SetQuerySettingsIndexHintAction, hint: QuerySettingsIndexHint | None) -> str:
    return hashlib.sha256(json.dumps(_state(action, hint), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
