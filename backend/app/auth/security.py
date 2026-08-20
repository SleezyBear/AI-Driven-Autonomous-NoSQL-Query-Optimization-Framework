"""Argon2 password protection, JWT principals, and fixed authorization rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, cast

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError


class Role(str, Enum):
    """The only control-plane authorization roles."""

    VIEWER = "VIEWER"
    OPERATOR = "OPERATOR"
    APPROVER = "APPROVER"
    ADMIN = "ADMIN"


class AuthorizationError(PermissionError):
    """Raised when an actor lacks authorization for a protected operation."""


@dataclass(frozen=True)
class Principal:
    """Authenticated control-plane identity and its single assigned role."""

    user_id: str
    role: Role


class PasswordService:
    """Hash and verify passwords with Argon2."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher()

    def hash_password(self, password: str) -> str:
        """Return an Argon2 password hash."""
        return cast(str, self._hasher.hash(password))

    def verify_password(self, password_hash: str, password: str) -> bool:
        """Return whether a password matches an Argon2 hash."""
        try:
            return cast(bool, self._hasher.verify(password_hash, password))
        except (InvalidHashError, VerifyMismatchError):
            return False


class JwtService:
    """Issue and verify JWTs containing only a principal identity and role."""

    def __init__(self, signing_key: str) -> None:
        self._signing_key = signing_key

    def issue(self, principal: Principal) -> str:
        """Issue a signed HS256 token for a principal."""
        token = jwt.encode(
            {"sub": principal.user_id, "role": principal.role.value},
            self._signing_key,
            algorithm="HS256",
        )
        return cast(str, token)

    def verify(self, token: str) -> Principal:
        """Verify a signed token and return its fixed-role principal."""
        claims = cast(dict[str, Any], jwt.decode(token, self._signing_key, algorithms=["HS256"]))
        subject = claims.get("sub")
        role_value = claims.get("role")
        if not isinstance(subject, str) or not isinstance(role_value, str):
            raise AuthorizationError("JWT is missing required principal claims.")
        try:
            return Principal(user_id=subject, role=Role(role_value))
        except ValueError as error:
            raise AuthorizationError("JWT contains an invalid role.") from error


def require_role(principal: Principal, *allowed_roles: Role) -> None:
    """Require one of the supplied fixed roles."""
    if principal.role not in allowed_roles:
        raise AuthorizationError("Principal does not have the required role.")


def require_approval_authority(principal: Principal, requested_by_user_id: str) -> None:
    """Require independent approval authority; self-approval is always forbidden."""
    require_role(principal, Role.APPROVER, Role.ADMIN)
    if principal.user_id == requested_by_user_id:
        raise AuthorizationError("An operator cannot approve their own request.")

