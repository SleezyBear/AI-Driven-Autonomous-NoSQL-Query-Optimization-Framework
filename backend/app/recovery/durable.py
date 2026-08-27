"""Durable idempotent production-action recovery using observed target state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class DurableRecovery:
    """Persist checkpoints before side effects and recover from actual target observation."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record_intent(self, *, idempotency_key: str, action_id: str, target_id: UUID, expected_fingerprint: str) -> None:
        now = datetime.now(timezone.utc)
        async with self._engine.begin() as connection:
            await connection.execute(text("INSERT INTO production_action_recovery (id, idempotency_key, action_id, target_id, expected_fingerprint, state, created_at, updated_at) VALUES (:id, :key, :action, :target, :fingerprint, 'INTENT_RECORDED', :now, :now) ON CONFLICT (idempotency_key) DO NOTHING"), {"id": uuid4(), "key": idempotency_key, "action": action_id, "target": target_id, "fingerprint": expected_fingerprint, "now": now})

    async def execute_or_recover(self, *, idempotency_key: str, target_has_exact_effect: Callable[[str], Awaitable[bool]], apply_mutation: Callable[[], Awaitable[None]]) -> str:
        async with self._engine.begin() as connection:
            result = await connection.execute(text("SELECT * FROM production_action_recovery WHERE idempotency_key = :key FOR UPDATE"), {"key": idempotency_key})
            record = result.mappings().one_or_none()
            if record is None:
                raise ValueError("idempotency intent must be recorded before execution")
            if record["state"] == "EXECUTION_CONFIRMED":
                return "EXECUTION_CONFIRMED"
            await connection.execute(text("UPDATE production_action_recovery SET state = 'EXECUTION_STARTED', updated_at = :now WHERE idempotency_key = :key"), {"key": idempotency_key, "now": datetime.now(timezone.utc)})
        if not await target_has_exact_effect(str(record["expected_fingerprint"])):
            await apply_mutation()
        async with self._engine.begin() as connection:
            await connection.execute(text("UPDATE production_action_recovery SET state = 'EFFECT_OBSERVED', updated_at = :now WHERE idempotency_key = :key"), {"key": idempotency_key, "now": datetime.now(timezone.utc)})
            await connection.execute(text("UPDATE production_action_recovery SET state = 'EXECUTION_CONFIRMED', updated_at = :now WHERE idempotency_key = :key"), {"key": idempotency_key, "now": datetime.now(timezone.utc)})
        return "EXECUTION_CONFIRMED"
