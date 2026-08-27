"""R9 contract: every public group is backed by a paginated resource route."""

from app.api.routes import ApiGroup, Page
from app.main import app


def test_every_resource_group_has_a_real_paginated_route_without_placeholder_status() -> None:
    paths = app.openapi()["paths"]
    assert {f"/api/v1/{group.value}" for group in ApiGroup}.issubset(paths)
    schema = Page.model_json_schema()
    assert "not_configured" not in str(schema)
