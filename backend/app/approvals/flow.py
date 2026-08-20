"""Approval flow that invalidates approval whenever its evidence changes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


class ApprovalStatus(str, Enum):
    """The possible states of one evidence-bound approval request."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    STALE = "STALE"


class ApprovalRequired(PermissionError):
    """Raised when a semi-autonomous action lacks current approved evidence."""


@dataclass(frozen=True)
class Approval:
    """A human approval bound immutably to one action and evidence hash."""

    approval_id: str
    action_id: str
    evidence_hash: str
    requested_at: datetime
    status: ApprovalStatus
    approved_by: str | None = None
    approved_at: datetime | None = None


class ApprovalFlow:
    """Keep approvals evidence-bound and reject stale approval at deployment time."""

    def __init__(self) -> None:
        self._approvals: dict[str, Approval] = {}

    def request(self, action_id: str, evidence_hash: str) -> Approval:
        """Request approval for a specific semi-autonomous action and evidence hash."""
        approval = Approval(
            approval_id=str(uuid4()),
            action_id=action_id,
            evidence_hash=evidence_hash,
            requested_at=datetime.now(timezone.utc),
            status=ApprovalStatus.PENDING,
        )
        self._approvals[approval.approval_id] = approval
        return approval

    def approve(self, approval_id: str, approver: str) -> Approval:
        """Record a human approval; stale approvals cannot be re-approved."""
        approval = self._approvals[approval_id]
        if approval.status is not ApprovalStatus.PENDING:
            raise ApprovalRequired(f"approval is not pending: {approval_id}")
        approved = replace(
            approval,
            status=ApprovalStatus.APPROVED,
            approved_by=approver,
            approved_at=datetime.now(timezone.utc),
        )
        self._approvals[approval_id] = approved
        return approved

    def require_current_approval(self, action_id: str, current_evidence_hash: str) -> Approval:
        """Return valid approval or fail closed, invalidating any evidence mismatch."""
        matching = [approval for approval in self._approvals.values() if approval.action_id == action_id]
        for approval in matching:
            if approval.status is ApprovalStatus.APPROVED and approval.evidence_hash != current_evidence_hash:
                self._approvals[approval.approval_id] = replace(approval, status=ApprovalStatus.STALE)

        for approval in self._approvals.values():
            if (
                approval.action_id == action_id
                and approval.status is ApprovalStatus.APPROVED
                and approval.evidence_hash == current_evidence_hash
            ):
                return approval
        raise ApprovalRequired(f"current approval required for semi-autonomous action: {action_id}")

    def get(self, approval_id: str) -> Approval:
        """Return a recorded approval state for audit and test inspection."""
        return self._approvals[approval_id]
