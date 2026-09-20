"""Centralized redaction for logs and externally visible error details."""

from __future__ import annotations

import re
from typing import Any

_SENSITIVE_KEY = re.compile(r"(authorization|cookie|password|access[_-]?token|refresh[_-]?token|aes|jwt|secret|key)", re.I)
_URI_CREDENTIALS = re.compile(
    r"((?:mongodb(?:\+srv)?|postgres(?:ql)?(?:\+asyncpg)?)://[^:/?#\s]+:)([^@/?#\s]+)(@)",
    re.I,
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")


def redact_value(value: Any, key: str | None = None) -> Any:
    """Return a recursive redacted copy without mutating caller-owned values."""
    if key is not None and _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact_value(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, str):
        return redact_connection_uri(value)
    return value


def redact_connection_uri(value: str) -> str:
    """Remove passwords and bearer/JWT tokens wherever they occur."""
    redacted = _URI_CREDENTIALS.sub(r"\1[REDACTED]\3", value)
    redacted = _BEARER.sub("Bearer [REDACTED]", redacted)
    return _JWT.sub("[REDACTED]", redacted)
