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

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}

