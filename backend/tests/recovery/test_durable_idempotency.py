"""R8 recovery acceptance: an effect observed after a worker crash is never replayed."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from sqlalchemy.ext.asyncio import create_async_engine
from app.recovery.durable import DurableRecovery


@pytest.mark.asyncio
async def test_restart_observes_exact_effect_and_never_creates_duplicate(disposable_recovery_database: str) -> None:
    key = f"r8-{uuid4()}"
    target_id = uuid4()
    created: list[str] = []

    async def has_exact_effect(fingerprint: str) -> bool:
        return created == [fingerprint]

    async def create_index() -> None:
        created.append("orders_status_fingerprint")

    first_engine = create_async_engine(disposable_recovery_database)
    first_worker = DurableRecovery(first_engine)
    await first_worker.record_intent(idempotency_key=key, action_id="create-index:orders_status", target_id=target_id, expected_fingerprint="orders_status_fingerprint")
    # Simulate MongoDB confirming the index, then kill the worker before it can confirm the workflow.
    await create_index()
    await first_engine.dispose()

    second_engine = create_async_engine(disposable_recovery_database)
    second_worker = DurableRecovery(second_engine)
    assert await second_worker.execute_or_recover(idempotency_key=key, target_has_exact_effect=has_exact_effect, apply_mutation=create_index) == "EXECUTION_CONFIRMED"
    assert created == ["orders_status_fingerprint"]
    async with second_engine.connect() as connection:
        state = await connection.scalar(text("SELECT state FROM production_action_recovery WHERE idempotency_key = :key"), {"key": key})
    assert state == "EXECUTION_CONFIRMED"
    await second_engine.dispose()
