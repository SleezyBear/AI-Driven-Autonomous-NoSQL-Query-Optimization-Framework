"""Tests for Phase 5 Argon2, JWT, and authorization boundaries."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth.routes import issue_test_token
from app.auth.security import JwtService, PasswordService, Principal, Role
from app.main import app


client = TestClient(app)


def authorization_header(principal: Principal) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_test_token(principal)}"}


def test_password_service_uses_argon2() -> None:
    service = PasswordService()
    password_hash = service.hash_password("correct horse battery staple")

    assert password_hash.startswith("$argon2")
    assert service.verify_password(password_hash, "correct horse battery staple")
    assert not service.verify_password(password_hash, "incorrect")


def test_jwt_round_trip_preserves_principal() -> None:
    service = JwtService("test-signing-key")
    principal = Principal(user_id="approver-1", role=Role.APPROVER)

    assert service.verify(service.issue(principal)) == principal


def test_unauthorized_operation_returns_403() -> None:
    response = client.post(
        "/operations/execute",
        headers=authorization_header(Principal(user_id="viewer-1", role=Role.VIEWER)),
    )

    assert response.status_code == 403


def test_operator_can_execute_operator_operation() -> None:
    response = client.post(
        "/operations/execute",
        headers=authorization_header(Principal(user_id="operator-1", role=Role.OPERATOR)),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "authorized"}


def test_operator_cannot_approve_own_request() -> None:
    response = client.post(
        "/approvals/request-1",
        json={"requested_by_user_id": "operator-1"},
        headers=authorization_header(Principal(user_id="operator-1", role=Role.APPROVER)),
    )

    assert response.status_code == 403


def test_independent_approver_can_approve() -> None:
    response = client.post(
        "/approvals/request-1",
        json={"requested_by_user_id": "operator-1"},
        headers=authorization_header(Principal(user_id="approver-1", role=Role.APPROVER)),
    )

    assert response.status_code == 200
    assert response.json() == {"request_id": "request-1", "status": "approved"}

