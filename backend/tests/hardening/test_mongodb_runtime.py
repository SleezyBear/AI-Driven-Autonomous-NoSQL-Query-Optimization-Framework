"""R23 centralized MongoDB connection policy contracts."""

from __future__ import annotations

from typing import Any

import pytest

from app.mongodb import client as mongo_runtime


def test_production_mongo_enforces_tls_topology_and_bounded_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, uri: str, **options: Any) -> None:
            captured.update({"uri": uri, **options})

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(mongo_runtime, "MongoClient", FakeClient)
    uri = "mongodb://service:opaque@mongo.example.invalid/admin?authSource=admin"
    mongo_runtime.create_mongo_client(uri)
    assert captured["tls"] is True
    assert captured["tlsAllowInvalidCertificates"] is False
    assert captured["serverSelectionTimeoutMS"] == 5_000
    assert captured["maxPoolSize"] == 20
    assert "directConnection" not in captured

    with pytest.raises(ValueError, match="topology discovery"):
        mongo_runtime.create_mongo_client(uri + "&directConnection=true")


def test_mongo_uri_redaction_never_returns_credentials() -> None:
    safe = mongo_runtime.safe_mongo_uri(
        "mongodb://user:password@example.invalid/db?authSource=admin&proxyPassword=hidden"
    )
    assert "user" not in safe
    assert "password" not in safe
    assert "hidden" not in safe
    assert "[REDACTED]" in safe
