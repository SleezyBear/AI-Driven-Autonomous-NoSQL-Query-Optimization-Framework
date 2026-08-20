"""Minimal protected endpoints used to enforce Phase 5 authorization boundaries."""

from __future__ import annotations

from secrets import token_urlsafe

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.auth.security import (
    AuthorizationError,
    JwtService,
    Principal,
    Role,
    require_approval_authority,
    require_role,
)


router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)
_jwt_service = JwtService(__import__("os").environ.get("JWT_SIGNING_KEY", token_urlsafe(48)))


class ApprovalRequest(BaseModel):
    """The request owner supplied when an approver records a decision."""

    requested_by_user_id: str


def current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Principal:
    """Resolve a principal or respond with the required authorization status."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authentication required.")
    try:
        return _jwt_service.verify(credentials.credentials)
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid credentials.") from error


@router.post("/operations/execute")
def execute_operator_operation(principal: Principal = Depends(current_principal)) -> dict[str, str]:
    """Require operator or administrator authority for an operator operation."""
    try:
        require_role(principal, Role.OPERATOR, Role.ADMIN)
    except AuthorizationError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    return {"status": "authorized"}


@router.post("/approvals/{request_id}")
def approve_request(
    request_id: str,
    approval_request: ApprovalRequest,
    principal: Principal = Depends(current_principal),
) -> dict[str, str]:
    """Require an independent approver or administrator for a request decision."""
    try:
        require_approval_authority(principal, approval_request.requested_by_user_id)
    except AuthorizationError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    return {"request_id": request_id, "status": "approved"}


def issue_test_token(principal: Principal) -> str:
    """Issue test-only endpoint tokens through the same JWT implementation."""
    return _jwt_service.issue(principal)
