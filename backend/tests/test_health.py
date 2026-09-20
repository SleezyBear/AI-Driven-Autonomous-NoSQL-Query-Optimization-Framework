"""Health endpoint tests."""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_live_health_endpoint() -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_ready_health_endpoint() -> None:
    response = client.get("/health/ready")

    # A client that bypasses application lifespan has no authoritative
    # PostgreSQL dependency and must fail closed.
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
