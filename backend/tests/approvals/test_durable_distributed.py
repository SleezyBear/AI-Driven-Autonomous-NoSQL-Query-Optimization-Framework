"""R5 process-boundary acceptance for PostgreSQL approval authority."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.approvals.durable import DurableApprovalRequired, DurableApprovalService
from app.auth.security import PasswordService
from app.db import models


async def create_identity(engine: object, email: str) -> UUID:
    identity = uuid4()
    now = datetime.now(timezone.utc)
    async with engine.begin() as connection:
        await connection.execute(models.User.__table__.insert().values(id=identity, created_at=now, updated_at=now, email=email, password_hash=PasswordService().hash_password("correct horse battery staple"), role="APPROVER", status="ACTIVE", failed_login_count=0))
    return identity


async def create_target(engine: object, owner: UUID) -> UUID:
    target_id = uuid4()
    now = datetime.now(timezone.utc)
    async with engine.begin() as connection:
        await connection.execute(models.Target.__table__.insert().values(id=target_id, created_at=now, updated_at=now, owner_user_id=owner, name="r5-target", deployment_mode="APPROVAL_CONTROLLED", state="ACTIVE", connection_label="r5", is_active=True))
    return target_id


@pytest.mark.asyncio
async def test_approval_is_visible_after_separate_process_restart_and_four_eyes(disposable_approval_database: str) -> None:
    setup_engine = create_async_engine(disposable_approval_database)
    requester = await create_identity(setup_engine, "r5-requester@example.com")
    approver = await create_identity(setup_engine, "r5-approver@example.com")
    target_id = await create_target(setup_engine, requester)
    await setup_engine.dispose()
    candidate_id = uuid4()
    engine_a = create_async_engine(disposable_approval_database)
    process_a = DurableApprovalService(engine_a)
    created = await process_a.request(action_id="create-index:orders_status", target_id=target_id, candidate_id=candidate_id, evidence_hash="evidence-r5", requester_id=requester)
    with pytest.raises(DurableApprovalRequired, match="four-eyes"):
        await process_a.approve(created["id"], requester)
    await engine_a.dispose()

    engine_b = create_async_engine(disposable_approval_database)
    process_b = DurableApprovalService(engine_b)
    approved = await process_b.approve(created["id"], approver)
    assert approved["status"] == "APPROVED"
    await engine_b.dispose()

    restarted_engine = create_async_engine(disposable_approval_database)
    after_restart = DurableApprovalService(restarted_engine)
    enforced = await after_restart.require_current(action_id="create-index:orders_status", target_id=target_id, candidate_id=candidate_id, evidence_hash="evidence-r5")
    assert enforced["id"] == created["id"]
    with pytest.raises(DurableApprovalRequired):
        await after_restart.require_current(action_id="create-index:orders_status", target_id=target_id, candidate_id=candidate_id, evidence_hash="different-evidence")
    await restarted_engine.dispose()


@pytest.mark.asyncio
async def test_expired_approval_cannot_be_enforced(disposable_approval_database: str) -> None:
    engine = create_async_engine(disposable_approval_database)
    requester = await create_identity(engine, "r5-expired@example.com")
    approver = await create_identity(engine, "r5-expired-approver@example.com")
    target_id = await create_target(engine, requester)
    service = DurableApprovalService(engine, approval_ttl=timedelta(milliseconds=-1))
    created = await service.request(action_id="create-index:orders_status", target_id=target_id, candidate_id=uuid4(), evidence_hash="evidence-r5", requester_id=requester)
    with pytest.raises(DurableApprovalRequired):
        await service.approve(created["id"], approver)
    await engine.dispose()
