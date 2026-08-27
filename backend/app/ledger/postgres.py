"""PostgreSQL append-only production ledger and persisted hash-chain verification."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine


GENESIS_HASH = "0" * 64


class PostgresProductionLedger:
    """Append records transactionally; ordinary database writes cannot mutate history."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def append(self, *, target_id: UUID, run_id: UUID | None, candidate_id: UUID | None, action_id: str, event_type: str, before_state: Mapping[str, Any], intended_state: Mapping[str, Any], after_state: Mapping[str, Any], forward_action: Mapping[str, Any], inverse_action: Mapping[str, Any], evidence_hash: str, actor: str) -> RowMapping:
        now = datetime.now(timezone.utc)
        async with self._engine.begin() as connection:
            previous = await connection.execute(text("SELECT sequence, entry_hash FROM production_ledger_entries WHERE target_id = :target_id ORDER BY sequence DESC LIMIT 1 FOR UPDATE"), {"target_id": target_id})
            prior = previous.mappings().one_or_none()
            sequence = 1 if prior is None else int(prior["sequence"]) + 1
            previous_hash = GENESIS_HASH if prior is None else str(prior["entry_hash"])
            payload: dict[str, Any] = {"entry_id": uuid4(), "sequence": sequence, "target_id": target_id, "run_id": run_id, "candidate_id": candidate_id, "action_id": action_id, "event_type": event_type, "before_state": dict(before_state), "intended_state": dict(intended_state), "after_state": dict(after_state), "forward_action": dict(forward_action), "inverse_action": dict(inverse_action), "evidence_hash": evidence_hash, "actor": actor, "previous_hash": previous_hash, "created_at": now}
            payload["entry_hash"] = _entry_hash(payload)
            result = await connection.execute(text("INSERT INTO production_ledger_entries (entry_id, sequence, target_id, run_id, candidate_id, action_id, event_type, before_state, intended_state, after_state, forward_action, inverse_action, evidence_hash, actor, previous_hash, entry_hash, created_at) VALUES (:entry_id, :sequence, :target_id, :run_id, :candidate_id, :action_id, :event_type, CAST(:before_state AS jsonb), CAST(:intended_state AS jsonb), CAST(:after_state AS jsonb), CAST(:forward_action AS jsonb), CAST(:inverse_action AS jsonb), :evidence_hash, :actor, :previous_hash, :entry_hash, :created_at) RETURNING *"), _sql_payload(payload))
            return result.mappings().one()

    async def verify_target(self, target_id: UUID) -> bool:
        async with self._engine.connect() as connection:
            result = await connection.execute(text("SELECT * FROM production_ledger_entries WHERE target_id = :target_id ORDER BY sequence"), {"target_id": target_id})
            rows = result.mappings().all()
        previous = GENESIS_HASH
        for expected_sequence, row in enumerate(rows, start=1):
            if row["sequence"] != expected_sequence or row["previous_hash"] != previous or row["entry_hash"] != _entry_hash(dict(row)):
                return False
            previous = str(row["entry_hash"])
        return True


class LedgerVerificationJob:
    """Worker-callable periodic verifier over persisted target chains."""

    def __init__(self, ledger: PostgresProductionLedger) -> None:
        self._ledger = ledger

    async def run(self, target_id: UUID) -> bool:
        return await self._ledger.verify_target(target_id)


def _sql_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    values = dict(payload)
    for name in ("before_state", "intended_state", "after_state", "forward_action", "inverse_action"):
        values[name] = json.dumps(values[name], sort_keys=True, separators=(",", ":"))
    return values


def _entry_hash(entry: Mapping[str, Any]) -> str:
    fields = ("entry_id", "sequence", "target_id", "run_id", "candidate_id", "action_id", "event_type", "before_state", "intended_state", "after_state", "forward_action", "inverse_action", "evidence_hash", "actor", "previous_hash", "created_at")
    canonical = {field: _canonical(entry.get(field)) for field in fields}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value
