"""Phase 19 acceptance tests for deterministic index generation."""

from app.candidates.index_generator import DeterministicIndexGenerator, FindQueryShape


def _shape(**changes: object) -> FindQueryShape:
    values: dict[str, object] = {"query_shape_hash": "shape-1", "database": "commerce", "collection": "orders", "equality_fields": ("customer_id",), "sort_fields": (("created_at", -1),), "range_fields": ("total",)}
    values.update(changes)
    return FindQueryShape(**values)


def test_frozen_equality_sort_range_pattern_is_generated() -> None:
    candidates = DeterministicIndexGenerator().generate(_shape())

    assert [candidate.pattern for candidate in candidates] == ["EQUALITY_SORT_RANGE"]
    assert [tuple((field.field, field.direction) for field in candidate.action.fields) for candidate in candidates] == [(('customer_id', 1), ('created_at', -1), ('total', 1))]


def test_candidates_and_fingerprints_are_deterministic_and_bounded() -> None:
    generator = DeterministicIndexGenerator()
    first = generator.generate(_shape(equality_fields=("b", "a"), range_fields=("r", "q")))
    second = generator.generate(_shape(equality_fields=("a", "b"), range_fields=("q", "r")))

    assert first == second
    assert len(first) <= 5
    assert len({candidate.candidate_fingerprint for candidate in first}) == len(first)


def test_candidates_exceeding_safe_five_field_limit_are_omitted() -> None:
    candidates = DeterministicIndexGenerator().generate(_shape(equality_fields=("a", "b", "c", "d"), range_fields=("e", "f")))

    assert all(len(candidate.action.fields) <= 5 for candidate in candidates)
