"""Phase 54 tests for the exact autonomous action allowlist."""

from app.autonomy.policy import DeploymentMode, approval_required


def test_full_autonomous_mode_bypasses_approval_only_for_the_two_allowed_actions() -> None:
    assert approval_required(DeploymentMode.FULL_AUTONOMOUS, "CREATE_INDEX") is False
    assert approval_required(DeploymentMode.FULL_AUTONOMOUS, "SET_QUERY_SETTINGS_INDEX_HINT") is False
    assert approval_required(DeploymentMode.FULL_AUTONOMOUS, "DROP_INDEX") is True
    assert approval_required(DeploymentMode.APPROVAL_CONTROLLED, "CREATE_INDEX") is True


def test_permanent_human_gates_remain_required_in_full_autonomous_mode() -> None:
    assert approval_required(DeploymentMode.FULL_AUTONOMOUS, "SET_QUERY_SETTINGS_INDEX_HINT", True) is True
