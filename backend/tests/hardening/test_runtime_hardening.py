"""R20 fail-closed HTTP/runtime hardening contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.runtime import runtime_settings, validate_startup_secrets


def test_production_rejects_unsafe_hosts_cors_and_weak_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://service:opaque@db/control")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="CORS"):
        runtime_settings()

    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://console.example.invalid")
    monkeypatch.setenv("ALLOWED_HOSTS", "*")
    with pytest.raises(RuntimeError, match="ALLOWED_HOSTS"):
        runtime_settings()

    monkeypatch.setenv("ALLOWED_HOSTS", "optimizer.example.invalid")
    monkeypatch.setenv("JWT_SIGNING_KEY", "short")
    with pytest.raises(RuntimeError, match="32"):
        validate_startup_secrets(runtime_settings())

    key = tmp_path / "master-key"
    key.write_bytes(b"x" * 31)
    monkeypatch.setenv("JWT_SIGNING_KEY", "production-signing-material-with-40-characters")
    monkeypatch.setenv("CONTROL_PLANE_MASTER_KEY_FILE", str(key))
    with pytest.raises(RuntimeError, match="exactly 32"):
        validate_startup_secrets(runtime_settings())


def test_request_bound_security_headers_metrics_and_correlation_id() -> None:
    client = TestClient(app)
    response = client.post(
        "/auth/login",
        content=b"x" * 1_048_577,
        headers={"Content-Type": "application/json", "X-Request-ID": "invalid value"},
    )
    assert response.status_code == 413
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-request-id"] != "invalid value"
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "nosql_optimizer_http_requests_total" in metrics.text


def test_readiness_converts_unexpected_dependency_failure_to_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnusableEngine:
        def connect(self) -> None:
            raise RuntimeError("stale event loop")

    monkeypatch.setattr(
        app.state, "control_plane_engine", UnusableEngine(), raising=False
    )

    response = TestClient(app).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
