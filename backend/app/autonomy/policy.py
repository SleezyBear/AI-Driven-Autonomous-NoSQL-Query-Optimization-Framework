"""The narrow Phase 54 full-autonomous approval-bypass boundary."""

from __future__ import annotations

from enum import Enum


class DeploymentMode(str, Enum):
    """Deployment modes; approval-controlled remains the default."""

    APPROVAL_CONTROLLED = "APPROVAL_CONTROLLED"
    FULL_AUTONOMOUS = "FULL_AUTONOMOUS"


_FULL_AUTONOMOUS_ACTION_TYPES = frozenset({"CREATE_INDEX", "SET_QUERY_SETTINGS_INDEX_HINT"})


def approval_required(
    mode: DeploymentMode,
    action_type: str,
    permanent_human_gate: bool = False,
) -> bool:
    """Return whether a current human approval is mandatory for this exact action."""
    if permanent_human_gate:
        return True
    return mode is not DeploymentMode.FULL_AUTONOMOUS or action_type not in _FULL_AUTONOMOUS_ACTION_TYPES
