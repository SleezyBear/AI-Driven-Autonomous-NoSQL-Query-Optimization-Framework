"""Approval flow that invalidates approval whenever its evidence changes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable
from enum import Enum
from uuid import uuid4


class ApprovalStatus(str, Enum):
    """The possible states of one evidence-bound approval request."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    STALE = "STALE"
    EXPIRED = "EXPIRED"


class ApprovalRequired(PermissionError):
    """Raised when a semi-autonomous action lacks current approved evidence."""


@dataclass(frozen=True)
class Approval:
    """A human approval bound immutably to one action and evidence hash."""

    approval_id: str
    action_id: str
    target_id: str
    evidence_hash: str
    requested_at: datetime
    expires_at: datetime
    status: ApprovalStatus
    approved_by: str | None = None
    approved_at: datetime | None = None


class ApprovalFlow:
    """Keep approvals evidence-bound and reject stale approval at deployment time."""

    def __init__(self, approval_ttl: timedelta = timedelta(minutes=15), now: Callable[[], datetime] | None = None) -> None:
        if approval_ttl <= timedelta():
            raise ValueError("approval TTL must be positive")
        self._approvals: dict[str, Approval] = {}
        self._approval_ttl = approval_ttl
        self._now = now or (lambda: datetime.now(timezone.utc))

    def request(self, action_id: str, evidence_hash: str, target_id: str) -> Approval:
        """Request approval bound to one action, target, evidence hash, and finite lifetime."""
        requested_at = self._now()
        approval = Approval(
            approval_id=str(uuid4()),
            action_id=action_id,
            target_id=target_id,
            evidence_hash=evidence_hash,
            requested_at=requested_at,
            expires_at=requested_at + self._approval_ttl,
            status=ApprovalStatus.PENDING,
        )
        self._approvals[approval.approval_id] = approval
        return approval

    def approve(self, approval_id: str, approver: str) -> Approval:
        """Record a human approval; stale approvals cannot be re-approved."""
        approval = self._approvals[approval_id]
        if approval.expires_at <= self._now():
            self._approvals[approval_id] = replace(approval, status=ApprovalStatus.EXPIRED)
            raise ApprovalRequired(f"approval has expired: {approval_id}")
        if approval.status is not ApprovalStatus.PENDING:
            raise ApprovalRequired(f"approval is not pending: {approval_id}")
        approved = replace(
            approval,
            status=ApprovalStatus.APPROVED,
            approved_by=approver,
            approved_at=self._now(),
        )
        self._approvals[approval_id] = approved
        return approved

    def require_current_approval(self, action_id: str, current_evidence_hash: str, target_id: str) -> Approval:
        """Return valid approval or fail closed, invalidating any evidence mismatch."""
        matching = [approval for approval in self._approvals.values() if approval.action_id == action_id]
        for approval in matching:
            if approval.status is ApprovalStatus.APPROVED and approval.expires_at <= self._now():
                self._approvals[approval.approval_id] = replace(approval, status=ApprovalStatus.EXPIRED)
            elif approval.status is ApprovalStatus.APPROVED and approval.evidence_hash != current_evidence_hash:
                self._approvals[approval.approval_id] = replace(approval, status=ApprovalStatus.STALE)

        for approval in self._approvals.values():
            if (
                approval.action_id == action_id
                and approval.status is ApprovalStatus.APPROVED
                and approval.evidence_hash == current_evidence_hash
                and approval.target_id == target_id
            ):
                return approval
        raise ApprovalRequired(f"current approval required for semi-autonomous action: {action_id}")

    def get(self, approval_id: str) -> Approval:
        """Return a recorded approval state for audit and test inspection."""
        return self._approvals[approval_id]
