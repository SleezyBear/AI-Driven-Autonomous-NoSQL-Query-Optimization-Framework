"""Fail-closed rollback for exactly ledger-owned index creations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, cast

from app.adapters.contracts import DatabaseAdapter, Namespace
from app.ledger.chain import AppendOnlyLedger, LedgerEntry


class RollbackStatus(str, Enum):
    """Outcome of an ownership-verified rollback attempt."""

    ROLLED_BACK = "ROLLED_BACK"
    ROLLBACK_BLOCKED = "ROLLBACK_BLOCKED"


@dataclass(frozen=True)
class RollbackRequest:
    """Identify one previously applied optimizer-owned index action."""

    target_id: str
    applied_ledger_entry_id: str
    actor: str


@dataclass(frozen=True)
class RollbackResult:
    """The result and reason codes for an attempted index rollback."""

    status: RollbackStatus
    reason_codes: tuple[str, ...]
    ledger_entry: LedgerEntry | None = None


class OwnedIndexRollbacker:
    """Remove an index only when all ownership and no-drift checks still hold."""

    def __init__(self, adapter: DatabaseAdapter, ledger: AppendOnlyLedger) -> None:
        self._adapter = adapter
        self._ledger = ledger

    async def rollback(self, request: RollbackRequest) -> RollbackResult:
        """Rollback the owned index or return ROLLBACK_BLOCKED without mutation."""
        entry = next((item for item in self._ledger.entries if item.entry_id == request.applied_ledger_entry_id), None)
        if entry is None:
            return RollbackResult(RollbackStatus.ROLLBACK_BLOCKED, ("LEDGER_OWNERSHIP_MISSING",))

        action = entry.forward_action
        failures = await self._verify_ownership(entry, action, request.target_id)
        if failures:
            return RollbackResult(RollbackStatus.ROLLBACK_BLOCKED, failures)

        namespace = Namespace(collection=str(action["collection"]))
        index_name = str(action["index_name"])
        before_state = await self._current_state(str(action["database"]), namespace)
        await self._adapter.drop_index(namespace, index_name)
        after_state = await self._current_state(str(action["database"]), namespace)
        if any(index["name"] == index_name for index in after_state["indexes"]):
            return RollbackResult(RollbackStatus.ROLLBACK_BLOCKED, ("RESULTING_STATE_MISMATCH",))

        rollback_entry = self._ledger.append(
            before_state=before_state,
            intended_state=after_state,
            after_state=after_state,
            forward_action={"phase": "ROLLED_BACK", **_thaw_mapping(entry.inverse_action)},
            inverse_action=_thaw_mapping(action),
            evidence_hash=entry.evidence_hash,
            actor=request.actor,
        )
        return RollbackResult(RollbackStatus.ROLLED_BACK, (), rollback_entry)

    async def _verify_ownership(
        self, entry: LedgerEntry, action: Mapping[str, Any], target_id: str
    ) -> tuple[str, ...]:
        failures: list[str] = []
        if action.get("phase") != "APPLIED" or action.get("action_type") != "CREATE_INDEX":
            failures.append("LEDGER_OWNERSHIP_MISSING")
            return tuple(failures)
        if action.get("target_id") != target_id:
            failures.append("TARGET_MISMATCH")
        database = action.get("database")
        collection = action.get("collection")
        if not isinstance(database, str) or not isinstance(collection, str):
            failures.append("NAMESPACE_MISMATCH")
            return tuple(failures)

        namespace = Namespace(collection=collection)
        current_state = await self._current_state(database, namespace)
        if not current_state["namespace_exists"]:
            failures.append("NAMESPACE_MISMATCH")
            return tuple(failures)
        matching = [index for index in current_state["indexes"] if index["name"] == action.get("index_name")]
        fields = action.get("fields", ())
        expected_keys = [
            (item["field"], item["direction"])
            for item in fields
            if isinstance(item, Mapping) and isinstance(item.get("field"), str) and isinstance(item.get("direction"), int)
        ]
        if len(matching) != 1 or matching[0]["keys"] != expected_keys:
            failures.append("INDEX_SPEC_MISMATCH")
        current_fingerprint = _index_fingerprint(matching[0]) if len(matching) == 1 else None
        if current_fingerprint != action.get("index_fingerprint"):
            failures.append("FINGERPRINT_MISMATCH")
        if _state_hash(current_state) != _state_hash(entry.after_state):
            failures.append("RELEVANT_DRIFT_DETECTED")
        return tuple(failures)

    async def _current_state(self, database: str, namespace: Namespace) -> dict[str, Any]:
        namespaces = await self._adapter.list_namespaces()
        indexes = await self._adapter.list_indexes(namespace) if namespace in namespaces else ()
        return {
            "database": database,
            "collection": namespace.collection,
            "namespace_exists": namespace in namespaces,
            "indexes": [{"name": index.name, "keys": list(index.keys)} for index in indexes],
        }


def _index_fingerprint(index: Mapping[str, Any]) -> str:
    """Fingerprint a current index exactly as the deployment ledger does."""
    payload = {"name": index["name"], "keys": index["keys"]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _state_hash(state: Mapping[str, Any]) -> str:
    """Canonicalize frozen ledger mappings and current state for drift comparison."""
    return hashlib.sha256(json.dumps(state, default=dict, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _thaw_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Convert recursively frozen ledger evidence back to JSON-shaped data."""
    return cast(dict[str, Any], json.loads(json.dumps(value, default=dict, sort_keys=True)))
