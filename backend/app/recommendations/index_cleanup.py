"""Recommendation-only detection of potentially removable indexes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CleanupReason(str, Enum):
    """The bounded, evidence-based cleanup categories."""

    UNUSED = "UNUSED"
    DUPLICATE = "DUPLICATE"
    REDUNDANT_PREFIX = "REDUNDANT_PREFIX"
    STALE_OPTIMIZER_OWNED = "STALE_OPTIMIZER_OWNED"


@dataclass(frozen=True)
class ObservedIndex:
    """Literal-free index metadata and observed-use evidence."""

    name: str
    keys: tuple[tuple[str, int], ...]
    observed_use_count: int
    optimizer_owned: bool


@dataclass(frozen=True)
class IndexCleanupRecommendation:
    """An advisory only; no delete command or deployment action is represented."""

    index_name: str
    reasons: tuple[CleanupReason, ...]
    optimizer_owned: bool


class IndexCleanupAdvisor:
    """Detect bounded cleanup evidence while never automatically dropping an index."""

    def recommend(self, indexes: tuple[ObservedIndex, ...]) -> tuple[IndexCleanupRecommendation, ...]:
        """Return deterministic recommendations for non-primary-key indexes only."""
        _validate_indexes(indexes)
        reasons: dict[str, set[CleanupReason]] = {index.name: set() for index in indexes}
        candidates = tuple(index for index in indexes if index.name != "_id_")
        for index in candidates:
            if index.observed_use_count == 0:
                reasons[index.name].add(CleanupReason.UNUSED)
                if index.optimizer_owned:
                    reasons[index.name].add(CleanupReason.STALE_OPTIMIZER_OWNED)

        for group in _duplicate_groups(candidates):
            for duplicate in group[1:]:
                reasons[duplicate.name].add(CleanupReason.DUPLICATE)
        for shorter in candidates:
            if any(
                shorter.keys != longer.keys
                and len(shorter.keys) < len(longer.keys)
                and longer.keys[: len(shorter.keys)] == shorter.keys
                for longer in candidates
            ):
                reasons[shorter.name].add(CleanupReason.REDUNDANT_PREFIX)

        return tuple(
            IndexCleanupRecommendation(index.name, tuple(sorted(reasons[index.name], key=lambda reason: reason.value)), index.optimizer_owned)
            for index in sorted(candidates, key=lambda item: item.name)
            if reasons[index.name]
        )


def _duplicate_groups(indexes: tuple[ObservedIndex, ...]) -> tuple[tuple[ObservedIndex, ...], ...]:
    groups: dict[tuple[tuple[str, int], ...], list[ObservedIndex]] = {}
    for index in indexes:
        groups.setdefault(index.keys, []).append(index)
    return tuple(tuple(sorted(group, key=lambda item: item.name)) for group in groups.values() if len(group) > 1)


def _validate_indexes(indexes: tuple[ObservedIndex, ...]) -> None:
    names = [index.name for index in indexes]
    if len(names) != len(set(names)) or any(not index.name or not index.keys or index.observed_use_count < 0 for index in indexes):
        raise ValueError("index observations require unique names, keys, and non-negative use counts")
