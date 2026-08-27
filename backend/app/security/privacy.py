"""Privacy boundaries for evidence, logs, persistence, and LLM requests."""

from __future__ import annotations

import hmac
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class PrivacyMode(str, Enum):
    """Supported literal-handling modes for optimizer evidence."""

    LOCAL_NORMALIZED = "LOCAL_NORMALIZED"
    STRICT_HASHED = "STRICT_HASHED"


_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_UUID = re.compile(r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b", re.I)
_IDENTIFIER = re.compile(r"\b[a-z][a-z0-9_]*-[a-z0-9-]*\d[a-z0-9-]*\b", re.I)
_QUOTED = re.compile(r"(['\"])(?:\\.|(?!\1).)*\1")


@dataclass(frozen=True)
class PrivacyBoundary:
    """Convert untrusted literals to safe evidence before any external boundary."""

    mode: PrivacyMode
    hmac_key: bytes | str | None = None

    def __post_init__(self) -> None:
        if self.mode is PrivacyMode.STRICT_HASHED and not self.hmac_key:
            raise ValueError("STRICT_HASHED privacy requires a non-empty HMAC key")

    def protect(self, value: Any) -> Any:
        """Recursively remove literal values while retaining structural evidence."""
        if isinstance(value, dict):
            return {
                self.pseudonymize_identifier(str(key)) if self.mode is PrivacyMode.STRICT_HASHED else str(key): self.protect(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.protect(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.protect(item) for item in value)
        if value is None or isinstance(value, bool):
            return value
        if self.mode is PrivacyMode.LOCAL_NORMALIZED:
            return _type_token(value)
        return "hmac-sha256:" + self._pseudonym(value)

    def pseudonymize_identifier(self, identifier: str) -> str:
        """Return a stable keyed pseudonym for a database, collection, or field name."""
        if self.mode is PrivacyMode.LOCAL_NORMALIZED:
            return identifier
        return "hmac-sha256:" + self._pseudonym(identifier)

    def serialize_for_postgres(self, evidence: Any) -> str:
        """Return safe JSON-shaped evidence suitable for PostgreSQL persistence."""
        return json.dumps(self.protect(evidence), sort_keys=True, separators=(",", ":"))

    def for_log(self, evidence: Any) -> Any:
        """Return a safe log payload without mutating caller-owned evidence."""
        return self.protect(evidence)

    def sanitize_prompt_text(self, prompt: str) -> str:
        """Remove common free-text literal forms before an Ollama request is captured."""
        replacement = "<literal>" if self.mode is PrivacyMode.LOCAL_NORMALIZED else "hmac-sha256:<redacted>"
        sanitized = _EMAIL.sub(replacement, prompt)
        sanitized = _UUID.sub(replacement, sanitized)
        sanitized = _IDENTIFIER.sub(replacement, sanitized)
        return _QUOTED.sub(replacement, sanitized)

    def _pseudonym(self, value: Any) -> str:
        key = self.hmac_key
        if isinstance(key, str):
            key = key.encode("utf-8")
        assert key is not None
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hmac.new(key, encoded.encode("utf-8"), "sha256").hexdigest()


def _type_token(value: Any) -> str:
    if isinstance(value, str):
        return "<string>"
    if isinstance(value, int):
        return "<integer>"
    if isinstance(value, float):
        return "<number>"
    return "<" + type(value).__name__ + ">"
