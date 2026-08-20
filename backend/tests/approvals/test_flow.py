"""Phase 31 acceptance tests for semi-autonomous approval."""

import pytest

from app.approvals.flow import ApprovalFlow, ApprovalRequired, ApprovalStatus


def test_semi_autonomous_action_requires_approved_current_evidence() -> None:
    flow = ApprovalFlow()
    requested = flow.request("candidate-1", "evidence-a")
    approved = flow.approve(requested.approval_id, "operator@example.test")

    current = flow.require_current_approval("candidate-1", "evidence-a")

    assert current == approved
    assert current.approved_by == "operator@example.test"


def test_stale_approval_cannot_deploy_after_evidence_changes() -> None:
    flow = ApprovalFlow()
    requested = flow.request("candidate-1", "evidence-a")
    flow.approve(requested.approval_id, "operator@example.test")

    with pytest.raises(ApprovalRequired, match="current approval required"):
        flow.require_current_approval("candidate-1", "evidence-b")

    assert flow.get(requested.approval_id).status is ApprovalStatus.STALE


def test_pending_approval_cannot_deploy() -> None:
    flow = ApprovalFlow()
    flow.request("candidate-1", "evidence-a")

    with pytest.raises(ApprovalRequired):
        flow.require_current_approval("candidate-1", "evidence-a")
