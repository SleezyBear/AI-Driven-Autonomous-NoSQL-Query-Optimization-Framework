"""Tests for Phase 5 Argon2, JWT, and authorization boundaries."""

from __future__ import annotations

import pytest

from app.auth.security import AuthorizationError, JwtService, PasswordService, Principal, Role, require_approval_authority, require_role


def test_password_service_uses_argon2() -> None:
    service = PasswordService()
    password_hash = service.hash_password("correct horse battery staple")

    assert password_hash.startswith("$argon2")
    assert service.verify_password(password_hash, "correct horse battery staple")
    assert not service.verify_password(password_hash, "incorrect")


def test_jwt_round_trip_preserves_principal() -> None:
    service = JwtService("test-signing-key-that-is-long-enough")
    principal = Principal(user_id="approver-1", role=Role.APPROVER)

    assert service.verify(service.issue(principal)) == principal


def test_viewer_cannot_execute_operator_operation() -> None:
    with pytest.raises(AuthorizationError):
        require_role(Principal(user_id="viewer-1", role=Role.VIEWER), Role.OPERATOR, Role.ADMIN)


def test_operator_cannot_approve_own_request() -> None:
    with pytest.raises(AuthorizationError):
        require_approval_authority(Principal(user_id="operator-1", role=Role.APPROVER), "operator-1")


def test_independent_approver_can_approve() -> None:
    require_approval_authority(Principal(user_id="approver-1", role=Role.APPROVER), "operator-1")
