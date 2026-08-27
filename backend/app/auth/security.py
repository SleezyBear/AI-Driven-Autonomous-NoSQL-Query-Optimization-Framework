"""Argon2 password protection, JWT principals, and fixed authorization rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, cast

import jwt
from argon2 import PasswordHasher, Type
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
        self._hasher = PasswordHasher(type=Type.ID)

    def hash_password(self, password: str) -> str:
        """Return an Argon2 password hash."""
        self._validate_password(password)
        return cast(str, self._hasher.hash(password))

    def verify_password(self, password_hash: str, password: str) -> bool:
        """Return whether a password matches an Argon2 hash."""
        if not 12 <= len(password) <= 128:
            return False
        try:
            return cast(bool, self._hasher.verify(password_hash, password))
        except (InvalidHashError, VerifyMismatchError):
            return False

    @staticmethod
    def _validate_password(password: str) -> None:
        if not 12 <= len(password) <= 128:
            raise ValueError("Password length must be between 12 and 128 characters.")


class JwtService:
    """Issue and verify JWTs containing only a principal identity and role."""

    def __init__(self, signing_key: str) -> None:
        if len(signing_key) < 32:
            raise ValueError("JWT signing key must contain at least 32 characters.")
        self._signing_key = signing_key

    def issue(self, principal: Principal, token_type: str = "access", token_id: str | None = None) -> str:
        """Issue a signed HS256 token for a principal."""
        if token_type not in {"access", "refresh"}:
            raise ValueError("Unsupported JWT token type.")
        now = datetime.now(timezone.utc)
        lifetime = timedelta(minutes=15) if token_type == "access" else timedelta(days=7)
        claims: dict[str, object] = {"sub": principal.user_id, "role": principal.role.value, "token_type": token_type, "iat": now, "exp": now + lifetime}
        if token_id is not None:
            claims["jti"] = token_id
        token = jwt.encode(
            claims,
            self._signing_key,
            algorithm="HS256",
        )
        return cast(str, token)

    def verify(self, token: str, expected_token_type: str = "access") -> Principal:
        """Verify a signed token and return its fixed-role principal."""
        try:
            claims = cast(dict[str, Any], jwt.decode(token, self._signing_key, algorithms=["HS256"], options={"require": ["exp", "iat", "sub", "token_type"]}))
        except jwt.PyJWTError as error:
            raise AuthorizationError("JWT is invalid or expired.") from error
        subject = claims.get("sub")
        role_value = claims.get("role")
        if not isinstance(subject, str) or not isinstance(role_value, str) or claims.get("token_type") != expected_token_type:
            raise AuthorizationError("JWT is missing required principal claims.")
        try:
            return Principal(user_id=subject, role=Role(role_value))
        except ValueError as error:
            raise AuthorizationError("JWT contains an invalid role.") from error

    def decode_claims(self, token: str, expected_token_type: str = "access") -> dict[str, Any]:
        """Return verified claims for a token of the requested type."""
        self.verify(token, expected_token_type)
        return cast(dict[str, Any], jwt.decode(token, self._signing_key, algorithms=["HS256"]))


def require_role(principal: Principal, *allowed_roles: Role) -> None:
    """Require one of the supplied fixed roles."""
    if principal.role not in allowed_roles:
        raise AuthorizationError("Principal does not have the required role.")


def require_approval_authority(principal: Principal, requested_by_user_id: str) -> None:
    """Require independent approval authority; self-approval is always forbidden."""
    require_role(principal, Role.APPROVER, Role.ADMIN)
    if principal.user_id == requested_by_user_id:
        raise AuthorizationError("An operator cannot approve their own request.")
