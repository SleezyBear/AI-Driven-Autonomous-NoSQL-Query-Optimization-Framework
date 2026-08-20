"""Phase 18 acceptance tests for reversible typed action schemas."""

import pytest
from pydantic import ValidationError

from app.actions.schemas import CreateIndexAction, RestoreQuerySettingsIndexHintAction, SetQuerySettingsIndexHintAction


def _index(**changes: object) -> CreateIndexAction:
    values: dict[str, object] = {"database": "commerce", "collection": "orders", "index_name": "customer_created", "fields": ({"field": "customer_id", "direction": 1},)}
    values.update(changes)
    return CreateIndexAction(**values)


def test_create_index_has_exact_typed_inverse() -> None:
    action = _index()
    assert action.inverse().model_dump() == {"action_type": "DROP_INDEX", "database": "commerce", "collection": "orders", "index_name": "customer_created"}


@pytest.mark.parametrize("field, value", [("unique", True), ("expire_after_seconds", 60), ("sparse", True), ("partial_filter_expression", {"status": "new"}), ("text", True), ("wildcard", True), ("geo", True), ("hashed", True)])
def test_every_forbidden_autonomous_index_variant_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _index(**{field: value})


def test_index_field_count_and_non_btree_key_type_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _index(fields=tuple({"field": f"field_{number}", "direction": 1} for number in range(6)))
    with pytest.raises(ValidationError):
        _index(fields=({"field": "location", "direction": "2dsphere"},))


def test_query_settings_inverse_restores_exact_prior_state() -> None:
    action = SetQuerySettingsIndexHintAction(database="commerce", collection="orders", query_shape_hash="shape", index_hint="new_hint", previous_index_hint="old_hint")
    inverse = action.inverse()

    assert isinstance(inverse, RestoreQuerySettingsIndexHintAction)
    assert inverse.index_hint == "old_hint"
