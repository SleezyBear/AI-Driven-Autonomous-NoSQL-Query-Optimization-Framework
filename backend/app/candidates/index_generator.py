"""Bounded deterministic MongoDB-find index generation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.actions.schemas import CreateIndexAction, IndexField


@dataclass(frozen=True)
class FindQueryShape:
    """Literal-free find-shape facts needed by the frozen initial index patterns."""

    query_shape_hash: str
    database: str
    collection: str
    equality_fields: tuple[str, ...]
    sort_fields: tuple[tuple[str, int], ...]
    range_fields: tuple[str, ...]


@dataclass(frozen=True)
class IndexCandidate:
    """A deterministic candidate identity bound to one typed CREATE_INDEX action."""

    candidate_fingerprint: str
    pattern: str
    action: CreateIndexAction


class DeterministicIndexGenerator:
    """Generate at most five safe candidates using only the frozen find patterns."""

    _PATTERNS = (
        ("EQUALITY_SORT_RANGE", ("equality", "sort", "range")),
        ("EQUALITY_RANGE_SORT", ("equality", "range", "sort")),
        ("EQUALITY_SORT", ("equality", "sort")),
    )

    def generate(self, shape: FindQueryShape) -> tuple[IndexCandidate, ...]:
        """Return stable, de-duplicated candidates in frozen pattern order."""
        groups = {
            "equality": tuple((field, 1) for field in sorted(set(shape.equality_fields))),
            "sort": tuple(sorted(shape.sort_fields)),
            "range": tuple((field, 1) for field in sorted(set(shape.range_fields))),
        }
        candidates: list[IndexCandidate] = []
        seen_key_patterns: set[tuple[tuple[str, int], ...]] = set()
        for pattern, group_names in self._PATTERNS:
            keys = tuple(item for group_name in group_names for item in groups[group_name])
            if not keys or len(keys) > 5 or keys in seen_key_patterns:
                continue
            seen_key_patterns.add(keys)
            fingerprint = self._fingerprint(shape, pattern, keys)
            action = CreateIndexAction(
                database=shape.database,
                collection=shape.collection,
                index_name=f"optimizer_{fingerprint[:16]}",
                fields=tuple(IndexField(field=field, direction=direction) for field, direction in keys),
            )
            candidates.append(IndexCandidate(fingerprint, pattern, action))
            if len(candidates) == 5:
                break
        return tuple(candidates)

    @staticmethod
    def _fingerprint(shape: FindQueryShape, pattern: str, keys: tuple[tuple[str, int], ...]) -> str:
        payload = {
            "collection": shape.collection,
            "database": shape.database,
            "keys": keys,
            "pattern": pattern,
            "query_shape_hash": shape.query_shape_hash,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
