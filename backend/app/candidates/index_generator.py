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
    """Generate the frozen v1 equality → sort → range CREATE_INDEX definition."""

    generation_rule_id = "candidate-generator-v1"
    generation_rule_version = "1"

    def generate(self, shape: FindQueryShape) -> tuple[IndexCandidate, ...]:
        """Return stable, de-duplicated candidates in frozen pattern order."""
        groups = {
            "equality": tuple((field, 1) for field in sorted(set(shape.equality_fields))),
            "sort": tuple(sorted(shape.sort_fields)),
            "range": tuple((field, 1) for field in sorted(set(shape.range_fields))),
        }
        seen_fields: set[str] = set()
        keys: list[tuple[str, int]] = []
        for group_name in ("equality", "sort", "range"):
            for field, direction in groups[group_name]:
                if field not in seen_fields:
                    seen_fields.add(field)
                    keys.append((field, direction))
        if not keys or len(keys) > 5:
            return ()
        frozen_keys = tuple(keys)
        pattern = "EQUALITY_SORT_RANGE"
        fingerprint = self._fingerprint(shape, pattern, frozen_keys)
        action = CreateIndexAction(
            database=shape.database,
            collection=shape.collection,
            index_name=f"optimizer_{fingerprint[:16]}",
            fields=tuple(IndexField(field=field, direction=direction) for field, direction in frozen_keys),
        )
        return (IndexCandidate(fingerprint, pattern, action),)

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
