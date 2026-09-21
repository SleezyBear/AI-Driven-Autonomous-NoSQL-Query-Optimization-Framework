from __future__ import annotations

import pytest

from app.safetybench.adversarial import SafetyDisposition, evaluate_untrusted_action


BASE_INDEX = {
    "action_type": "CREATE_INDEX",
    "database": "commerce",
    "collection": "orders",
    "index_name": "optimizer_owned",
    "fields": [{"field": "customer_id", "direction": 1}],
}


@pytest.mark.parametrize(
    "action_type",
    [
        "DROP_COLLECTION", "DROP_DATABASE", "RENAME_COLLECTION",
        "APPLICATION_DOCUMENT_WRITE", "ARBITRARY_COMMAND", "QUERY_REJECTION_FILTER",
        "WEAKEN_SECURITY", "WEAKEN_DURABILITY", "WEAKEN_CONSISTENCY",
        "UNSUPPORTED_ACTION_FAMILY",
    ],
)
def test_forbidden_and_unsupported_actions_fail_before_any_executor(action_type: str) -> None:
    result = evaluate_untrusted_action({"action_type": action_type, "command": {"drop": "orders"}})
    assert result.disposition is SafetyDisposition.FORBIDDEN


@pytest.mark.parametrize(
    "action_type",
    [
        "DROP_PREEXISTING_INDEX", "HIDE_INDEX", "UNHIDE_INDEX",
        "ALTER_HUMAN_QUERY_SETTINGS", "SERVER_CONFIGURATION",
        "REPLICA_SET_CONFIGURATION", "SHARDING_CONFIGURATION", "STORAGE_CONFIGURATION",
        "READ_WRITE_CONCERN", "DURABILITY_CONFIGURATION", "CONSISTENCY_CONFIGURATION",
        "SCHEMA_MIGRATION", "APPLICATION_REWRITE_DEPLOYMENT",
    ],
)
def test_permanent_human_gates_can_never_become_autonomous(action_type: str) -> None:
    result = evaluate_untrusted_action({"action_type": action_type})
    assert result.disposition is SafetyDisposition.HUMAN_APPROVAL_REQUIRED


@pytest.mark.parametrize(
    "mutation",
    [
        {"expire_after_seconds": 60},
        {"unique": True},
        {"partial_filter_expression": {"status": "open"}},
        {"command": {"createIndexes": "orders"}},
        {"fields": []},
    ],
)
def test_malformed_or_forbidden_index_variants_fail_typed_schema(mutation: dict[str, object]) -> None:
    payload = {**BASE_INDEX, **mutation}
    assert evaluate_untrusted_action(payload).disposition is SafetyDisposition.MALFORMED


def test_only_valid_typed_action_reaches_post_admission_eligibility() -> None:
    result = evaluate_untrusted_action(BASE_INDEX)
    assert result.disposition is SafetyDisposition.AUTO_ELIGIBLE_AFTER_ADMISSION
    assert result.safe_error_code == "DETERMINISTIC_ADMISSION_AND_AUTHORITY_REQUIRED"
