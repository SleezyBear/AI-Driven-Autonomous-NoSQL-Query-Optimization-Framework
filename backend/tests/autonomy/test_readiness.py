import json
from pathlib import Path

from app.autonomy.readiness import (
    AUTO_ELIGIBLE_ACTIONS,
    AUTONOMY_READINESS_MATRIX,
    ActionAuthority,
    matrix_document,
)


def test_only_frozen_typed_actions_are_autonomy_eligible() -> None:
    assert AUTO_ELIGIBLE_ACTIONS == {
        "CREATE_INDEX",
        "SET_QUERY_SETTINGS_INDEX_HINT",
    }
    assert all(
        not row.full_autonomous_deployable
        for row in AUTONOMY_READINESS_MATRIX
        if row.authority
        in {
            ActionAuthority.PERMANENTLY_HUMAN_GATED,
            ActionAuthority.RECOMMENDATION_ONLY,
            ActionAuthority.FORBIDDEN,
        }
    )


def test_documented_matrix_exactly_matches_executable_policy() -> None:
    path = Path(__file__).resolve().parents[3] / "docs" / "AUTONOMY_READINESS_MATRIX.json"
    assert json.loads(path.read_text(encoding="utf-8")) == matrix_document()
