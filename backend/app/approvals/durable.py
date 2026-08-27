"""PostgreSQL-backed four-eyes approvals shared by every API and worker process."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import models


class DurableApprovalRequired(PermissionError):
    """Raised when no unexpired, evidence-bound approval can authorize an action."""


class DurableApprovalService:
    """A transactionally consistent approval authority, not an in-memory cache."""

    def __init__(self, engine: AsyncEngine, approval_ttl: timedelta = timedelta(minutes=15)) -> None:
        self._engine = engine
        self._approval_ttl = approval_ttl

    async def request(self, *, action_id: str, target_id: UUID, candidate_id: UUID, evidence_hash: str, requester_id: UUID) -> RowMapping:
        now = datetime.now(timezone.utc)
        payload = {"id": uuid4(), "created_at": now, "updated_at": now, "admission_decision_id": None, "requested_by_user_id": requester_id, "action_id": action_id, "target_id": target_id, "candidate_id": candidate_id, "evidence_hash": evidence_hash, "expires_at": now + self._approval_ttl, "status": "PENDING"}
        async with self._engine.begin() as connection:
            result = await connection.execute(insert(models.ApprovalRequest.__table__).values(**payload).returning(*models.ApprovalRequest.__table__.c))
            return result.mappings().one()

    async def approve(self, approval_id: UUID, approver_id: UUID) -> RowMapping:
        now = datetime.now(timezone.utc)
        async with self._engine.begin() as connection:
            result = await connection.execute(select(models.ApprovalRequest.__table__).where(models.ApprovalRequest.id == approval_id).with_for_update())
            request = result.mappings().one_or_none()
            if request is None or request["status"] != "PENDING" or request["expires_at"] <= now:
                raise DurableApprovalRequired("approval is not pending and unexpired")
            if request["requested_by_user_id"] == approver_id:
                raise DurableApprovalRequired("four-eyes separation forbids self-approval")
            await connection.execute(update(models.ApprovalRequest.__table__).where(models.ApprovalRequest.id == approval_id).values(status="APPROVED", updated_at=now))
            decision = {"id": uuid4(), "created_at": now, "updated_at": now, "approval_request_id": approval_id, "decided_by_user_id": approver_id, "decision": "APPROVED", "reason": None}
            await connection.execute(insert(models.ApprovalDecision.__table__).values(**decision))
            approved = await connection.execute(select(models.ApprovalRequest.__table__).where(models.ApprovalRequest.id == approval_id))
            return approved.mappings().one()

    async def require_current(self, *, action_id: str, target_id: UUID, candidate_id: UUID, evidence_hash: str) -> RowMapping:
        now = datetime.now(timezone.utc)
        async with self._engine.begin() as connection:
            result = await connection.execute(select(models.ApprovalRequest.__table__).where(and_(models.ApprovalRequest.action_id == action_id, models.ApprovalRequest.target_id == target_id, models.ApprovalRequest.candidate_id == candidate_id, models.ApprovalRequest.evidence_hash == evidence_hash, models.ApprovalRequest.status == "APPROVED", models.ApprovalRequest.expires_at > now)).with_for_update())
            approval = result.mappings().one_or_none()
            if approval is None:
                raise DurableApprovalRequired("current approval required")
            return approval
