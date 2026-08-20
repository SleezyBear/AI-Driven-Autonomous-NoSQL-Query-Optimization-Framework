"""Phase 38 acceptance tests for recommendation-only index cleanup."""

from app.recommendations.index_cleanup import (
    CleanupReason,
    IndexCleanupAdvisor,
    ObservedIndex,
)


def _index(name: str, keys: tuple[tuple[str, int], ...], uses: int, owned: bool = False) -> ObservedIndex:
    return ObservedIndex(name, keys, uses, owned)


def test_detects_unused_and_stale_optimizer_owned_indexes() -> None:
    recommendations = IndexCleanupAdvisor().recommend(
        (_index("optimizer_old", (("status", 1),), 0, owned=True),)
    )

    assert recommendations[0].index_name == "optimizer_old"
    assert set(recommendations[0].reasons) == {CleanupReason.UNUSED, CleanupReason.STALE_OPTIMIZER_OWNED}


def test_detects_duplicate_and_redundant_prefix_indexes_deterministically() -> None:
    recommendations = IndexCleanupAdvisor().recommend(
        (
            _index("customer", (("customer_id", 1),), 5),
            _index("customer_copy", (("customer_id", 1),), 5),
            _index("customer_created", (("customer_id", 1), ("created_at", -1)), 5),
        )
    )
    by_name = {item.index_name: set(item.reasons) for item in recommendations}

    assert by_name["customer"] == {CleanupReason.REDUNDANT_PREFIX}
    assert by_name["customer_copy"] == {CleanupReason.DUPLICATE, CleanupReason.REDUNDANT_PREFIX}


def test_human_created_indexes_are_recommendations_only_and_primary_key_is_excluded() -> None:
    advisor = IndexCleanupAdvisor()
    recommendations = advisor.recommend(
        (_index("_id_", (("_id", 1),), 0), _index("human_unused", (("region", 1),), 0))
    )

    assert [item.index_name for item in recommendations] == ["human_unused"]
    assert recommendations[0].optimizer_owned is False
    assert not hasattr(advisor, "drop")
