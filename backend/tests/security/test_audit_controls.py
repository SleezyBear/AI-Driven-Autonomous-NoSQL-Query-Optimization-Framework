"""Explicit regression tests for the pre-Phase-15 HTTP and secret controls."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.security import JwtService, PasswordService, Principal, Role
from app.main import app
from app.security.redaction import redact_value


def test_redaction_removes_uri_password_and_sensitive_fields() -> None:
    redacted = redact_value({"Authorization": "Bearer token", "uri": "mongodb://user:secret@example/db", "nested": {"password": "hidden"}})

    assert redacted == {"Authorization": "[REDACTED]", "uri": "mongodb://user:[REDACTED]@example/db", "nested": {"password": "[REDACTED]"}}


def test_password_bounds_and_jwt_token_type_are_enforced() -> None:
    password_service = PasswordService()
    with pytest.raises(ValueError):
        password_service.hash_password("short")
    service = JwtService("a" * 48)
    refresh = service.issue(Principal("user", Role.OPERATOR), "refresh")
    with pytest.raises(Exception):
        service.verify(refresh, "access")


def test_request_id_and_explicit_cors_origin_are_returned() -> None:
    client = TestClient(app)
    response = client.get("/health/live", headers={"X-Request-ID": "audit-request"})
    preflight = client.options("/health/live", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})

    assert response.headers["X-Request-ID"] == "audit-request"
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"
