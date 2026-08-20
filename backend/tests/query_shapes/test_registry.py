"""Tests for server-hash preference and literal-free query shape fallback."""

from __future__ import annotations

from app.query_shapes.registry import QueryShapeRegistry, QueryShapeSource


def test_multiple_literal_values_map_to_one_canonical_query_shape() -> None:
    registry = QueryShapeRegistry()
    first = registry.register(
        "find", "commerce.orders", {"customer_email": "first@example.com", "total": {"$gt": 10}}
    )
    second = registry.register(
        "find", "commerce.orders", {"customer_email": "second@example.com", "total": {"$gt": 99}}
    )

    assert first.shape_hash == second.shape_hash
    assert first.canonical_shape == second.canonical_shape
    assert "first@example.com" not in first.canonical_shape
    assert "second@example.com" not in second.canonical_shape
    assert "<string>" in first.canonical_shape
    assert "<integer>" in first.canonical_shape


def test_server_query_shape_hash_is_preferred() -> None:
    registry = QueryShapeRegistry()

    shape = registry.register(
        "find",
        "commerce.orders",
        {"customer_email": "customer@example.com"},
        server_query_shape_hash="server-query-shape-hash",
    )

    assert shape.shape_hash == "server-query-shape-hash"
    assert shape.source is QueryShapeSource.SERVER_HASH
    assert "customer@example.com" not in shape.canonical_shape

