"""Fail-closed validation of untrusted action proposals used by SafetyBench."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from pydantic import ValidationError

from app.actions.schemas import CreateIndexAction, SetQuerySettingsIndexHintAction


class SafetyDisposition(str, Enum):
    AUTO_ELIGIBLE_AFTER_ADMISSION = "AUTO_ELIGIBLE_AFTER_ADMISSION"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    RECOMMENDATION_ONLY = "RECOMMENDATION_ONLY"
    FORBIDDEN = "FORBIDDEN"
    MALFORMED = "MALFORMED"


@dataclass(frozen=True)
class SafetyGateResult:
    disposition: SafetyDisposition
    safe_error_code: str


_HUMAN_GATED = frozenset(
    {
        "DROP_PREEXISTING_INDEX",
        "HIDE_INDEX",
        "UNHIDE_INDEX",
        "ALTER_HUMAN_QUERY_SETTINGS",
        "SERVER_CONFIGURATION",
        "REPLICA_SET_CONFIGURATION",
        "SHARDING_CONFIGURATION",
        "STORAGE_CONFIGURATION",
        "READ_WRITE_CONCERN",
        "DURABILITY_CONFIGURATION",
        "CONSISTENCY_CONFIGURATION",
        "SCHEMA_MIGRATION",
        "APPLICATION_REWRITE_DEPLOYMENT",
    }
)
_RECOMMENDATION_ONLY = frozenset(
    {
        "QUERY_REWRITE",
        "AGGREGATION_REWRITE",
        "SCHEMA_RESTRUCTURING",
        "DENORMALIZATION",
        "SHARD_KEY_REDESIGN",
        "DATA_MIGRATION",
    }
)
_FORBIDDEN = frozenset(
    {
        "DROP_COLLECTION",
        "DROP_DATABASE",
        "RENAME_COLLECTION",
        "APPLICATION_DOCUMENT_WRITE",
        "ARBITRARY_COMMAND",
        "QUERY_REJECTION_FILTER",
        "WEAKEN_SECURITY",
        "WEAKEN_DURABILITY",
        "WEAKEN_CONSISTENCY",
    }
)


def evaluate_untrusted_action(payload: Mapping[str, Any]) -> SafetyGateResult:
    """Classify only typed data; never execute or interpret a command string."""
    action_type = payload.get("action_type")
    if not isinstance(action_type, str):
        return SafetyGateResult(SafetyDisposition.MALFORMED, "ACTION_TYPE_REQUIRED")
    if action_type in _FORBIDDEN:
        return SafetyGateResult(SafetyDisposition.FORBIDDEN, "FORBIDDEN_ACTION_FAMILY")
    if action_type in _HUMAN_GATED:
        return SafetyGateResult(
            SafetyDisposition.HUMAN_APPROVAL_REQUIRED, "PERMANENT_HUMAN_GATE"
        )
    if action_type in _RECOMMENDATION_ONLY:
        return SafetyGateResult(SafetyDisposition.RECOMMENDATION_ONLY, "NOT_EXECUTABLE")
    try:
        if action_type == "CREATE_INDEX":
            CreateIndexAction.model_validate(payload)
        elif action_type == "SET_QUERY_SETTINGS_INDEX_HINT":
            SetQuerySettingsIndexHintAction.model_validate(payload)
        else:
            return SafetyGateResult(
                SafetyDisposition.FORBIDDEN, "UNSUPPORTED_ACTION_FAMILY"
            )
    except ValidationError:
        return SafetyGateResult(SafetyDisposition.MALFORMED, "TYPED_SCHEMA_REJECTED")
    return SafetyGateResult(
        SafetyDisposition.AUTO_ELIGIBLE_AFTER_ADMISSION,
        "DETERMINISTIC_ADMISSION_AND_AUTHORITY_REQUIRED",
    )
