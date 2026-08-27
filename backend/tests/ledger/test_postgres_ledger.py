"""R7 persisted ledger acceptance, including privileged tamper detection."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.runtime import create_control_plane_engine
from app.ledger.postgres import LedgerVerificationJob, PostgresProductionLedger


@pytest.mark.asyncio
async def test_persisted_chain_survives_restart_and_detects_privileged_tampering() -> None:
    target_id = uuid4()
    engine = create_control_plane_engine()
    ledger = PostgresProductionLedger(engine)
    entry = await ledger.append(target_id=target_id, run_id=None, candidate_id=None, action_id="create-index:orders_status", event_type="APPLIED", before_state={"indexes": []}, intended_state={"indexes": ["orders_status"]}, after_state={"indexes": ["orders_status"]}, forward_action={"type": "CREATE_INDEX"}, inverse_action={"type": "DROP_INDEX"}, evidence_hash="r7-evidence", actor="r7-worker")
    assert await LedgerVerificationJob(ledger).run(target_id)
    await engine.dispose()

    restarted_engine = create_control_plane_engine()
    restarted = PostgresProductionLedger(restarted_engine)
    assert await restarted.verify_target(target_id)
    async with restarted_engine.begin() as connection:
        await connection.execute(text("SELECT set_config('app.ledger_test_tamper', 'on', true)"))
        await connection.execute(text("UPDATE production_ledger_entries SET after_state = CAST(:state AS jsonb) WHERE entry_id = :entry_id"), {"state": '{\"indexes\":[\"tampered\"]}', "entry_id": entry["entry_id"]})
    assert not await restarted.verify_target(target_id)
    await restarted_engine.dispose()
