"""Query-shape identity without storing predicate literals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class QueryShapeSource(str, Enum):
    """The source that established query-shape identity."""

    SERVER_HASH = "SERVER_HASH"
    CANONICALIZED = "CANONICALIZED"


@dataclass(frozen=True)
class QueryShape:
    """A persistable query-shape record that contains no literal predicate values."""

    shape_hash: str
    source: QueryShapeSource
    canonical_shape: str


def _type_token(value: Any) -> str:
    if value is None:
        return "<null>"
    if isinstance(value, bool):
        return "<boolean>"
    if isinstance(value, int):
        return "<integer>"
    if isinstance(value, float):
        return "<number>"
    if isinstance(value, str):
        return "<string>"
    return f"<{type(value).__name__.lower()}>"


def canonicalize(value: Any) -> Any:
    """Replace every non-structural literal with a stable type token."""
    if isinstance(value, dict):
        return {key: canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [canonicalize(item) for item in value]
    if isinstance(value, tuple):
        return [canonicalize(item) for item in value]
    return _type_token(value)


class QueryShapeRegistry:
    """Register server or locally derived query shapes without retaining literals."""

    def __init__(self) -> None:
        self._shapes: dict[str, QueryShape] = {}

    def register(
        self,
        operation: str,
        namespace: str,
        query: dict[str, Any],
        server_query_shape_hash: str | None = None,
    ) -> QueryShape:
        """Register a shape, preferring the supplied MongoDB server hash."""
        canonical_payload = {
            "namespace": namespace,
            "operation": operation,
            "query": canonicalize(query),
        }
        canonical_shape = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))
        if server_query_shape_hash is not None:
            shape_hash = server_query_shape_hash
            source = QueryShapeSource.SERVER_HASH
        else:
            shape_hash = hashlib.sha256(canonical_shape.encode("utf-8")).hexdigest()
            source = QueryShapeSource.CANONICALIZED

        shape = QueryShape(shape_hash=shape_hash, source=source, canonical_shape=canonical_shape)
        self._shapes[shape_hash] = shape
        return shape

    def get(self, shape_hash: str) -> QueryShape | None:
        """Return a previously registered literal-free shape record."""
        return self._shapes.get(shape_hash)

