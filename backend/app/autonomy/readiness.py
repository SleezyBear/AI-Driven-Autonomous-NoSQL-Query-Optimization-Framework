"""Frozen, machine-verifiable autonomy and predeployment integrity policy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping


class ActionAuthority(str, Enum):
    AUTO_ELIGIBLE_AFTER_ADMISSION = "AUTO_ELIGIBLE_AFTER_ADMISSION"
    PERMANENTLY_HUMAN_GATED = "PERMANENTLY_HUMAN_GATED"
    RECOMMENDATION_ONLY = "RECOMMENDATION_ONLY"
    FORBIDDEN = "FORBIDDEN"
    OPTIMIZER_OWNED_INVERSE_ONLY = "OPTIMIZER_OWNED_INVERSE_ONLY"


@dataclass(frozen=True)
class AutonomyReadinessRow:
    action_family: str
    authority: ActionAuthority
    full_autonomous_deployable: bool
    approval_requirement: str
    telemetry_requirement: str
    target_capability_requirement: str
    rollback_requirement: str
    monitoring_required: bool


AUTONOMY_READINESS_MATRIX = (
    AutonomyReadinessRow("CREATE_INDEX", ActionAuthority.AUTO_ELIGIBLE_AFTER_ADMISSION, True, "fallback when any autonomy prerequisite fails", "production_autonomy_eligible=true", "typed index operations supported", "exact optimizer-owned DROP_INDEX inverse", True),
    AutonomyReadinessRow("SET_QUERY_SETTINGS_INDEX_HINT", ActionAuthority.AUTO_ELIGIBLE_AFTER_ADMISSION, True, "fallback when any autonomy prerequisite fails", "production_autonomy_eligible=true", "query settings supported", "exact optimizer-owned prior-setting restore", True),
    AutonomyReadinessRow("OPTIMIZER_OWNED_EXACT_INVERSE", ActionAuthority.OPTIMIZER_OWNED_INVERSE_ONLY, True, "none only for verified optimizer ownership", "persisted deployment evidence", "inverse supported", "idempotent and drift-checked", True),
    AutonomyReadinessRow("PRE_EXISTING_INDEX_CHANGE", ActionAuthority.PERMANENTLY_HUMAN_GATED, False, "always", "not applicable", "metadata read supported", "human-owned resource must never be removed", True),
    AutonomyReadinessRow("HUMAN_QUERY_SETTINGS_CHANGE", ActionAuthority.PERMANENTLY_HUMAN_GATED, False, "always", "not applicable", "query settings supported", "human-created setting must never be altered", True),
    AutonomyReadinessRow("SERVER_REPLICA_SHARD_STORAGE_DURABILITY_CONSISTENCY_CONFIG", ActionAuthority.PERMANENTLY_HUMAN_GATED, False, "always", "not applicable", "not autonomously supported", "not autonomously executable", True),
    AutonomyReadinessRow("SCHEMA_MIGRATION_OR_APPLICATION_REWRITE_DEPLOYMENT", ActionAuthority.PERMANENTLY_HUMAN_GATED, False, "always", "not applicable", "not autonomously supported", "not autonomously executable", True),
    AutonomyReadinessRow("QUERY_AGGREGATION_SCHEMA_DENORMALIZATION_SHARD_KEY_DATA_MIGRATION", ActionAuthority.RECOMMENDATION_ONLY, False, "not deployable", "diagnostic evidence only", "not executable", "not applicable", False),
    AutonomyReadinessRow("DOCUMENT_WRITE_OR_DESTRUCTIVE_DATABASE_OPERATION", ActionAuthority.FORBIDDEN, False, "forbidden", "not applicable", "not executable", "not applicable", False),
    AutonomyReadinessRow("TTL_INDEX_OR_QUERY_REJECTION_OR_SECURITY_WEAKENING", ActionAuthority.FORBIDDEN, False, "forbidden", "not applicable", "not executable", "not applicable", False),
)


AUTO_ELIGIBLE_ACTIONS = frozenset(
    row.action_family
    for row in AUTONOMY_READINESS_MATRIX
    if row.authority is ActionAuthority.AUTO_ELIGIBLE_AFTER_ADMISSION
)


def matrix_document() -> dict[str, Any]:
    """Return a stable JSON-shaped policy document for CI and operators."""
    return {
        "schema_version": 1,
        "rows": [
            {**asdict(row), "authority": row.authority.value}
            for row in AUTONOMY_READINESS_MATRIX
        ],
    }


def environment_binding(
    target: Mapping[str, Any],
    capability: Mapping[str, Any] | None,
    credential: Mapping[str, Any] | None,
) -> tuple[str, str, str]:
    """Fingerprint identity/capability/security facts without secret material."""
    identity = _hash(
        {
            "id": target["id"],
            "connection_label": target["connection_label"],
            "deployment_mode": target["deployment_mode"],
            "state": target["state"],
            "active": target["is_active"],
        }
    )
    capability_fingerprint = (
        str(capability["fingerprint"]) if capability is not None else "NO_CAPABILITY_SNAPSHOT"
    )
    security = _hash(
        {
            "credential_id": credential["id"] if credential is not None else None,
            "key_version": credential["key_version"] if credential is not None else None,
            "credential_type": credential["credential_type"] if credential is not None else None,
        }
    )
    return identity, capability_fingerprint, security


def authority_integrity_fingerprint(
    run_id: object,
    candidate_id: object,
    candidate_fingerprint: str,
    deployment_mode: str,
    authority_type: str,
    authority_reason: str,
    telemetry_eligible: bool,
    admission_production_eligible: bool,
    target_identity_fingerprint: str,
    capability_fingerprint: str,
    security_fingerprint: str,
) -> str:
    return _hash(
        {
            "run_id": run_id,
            "candidate_id": candidate_id,
            "candidate_fingerprint": candidate_fingerprint,
            "deployment_mode": deployment_mode,
            "authority_type": authority_type,
            "authority_reason": authority_reason,
            "telemetry_eligible": telemetry_eligible,
            "admission_production_eligible": admission_production_eligible,
            "target_identity_fingerprint": target_identity_fingerprint,
            "capability_fingerprint": capability_fingerprint,
            "security_fingerprint": security_fingerprint,
        }
    )


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
