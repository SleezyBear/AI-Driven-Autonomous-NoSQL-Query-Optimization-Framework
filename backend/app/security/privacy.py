"""Privacy boundaries for evidence, logs, persistence, and LLM requests."""

from __future__ import annotations

import hashlib
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

    def protect(self, value: Any) -> Any:
        """Recursively remove literal values while retaining structural evidence."""
        if isinstance(value, dict):
            return {str(key): self.protect(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.protect(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.protect(item) for item in value)
        if value is None or isinstance(value, bool):
            return value
        if self.mode is PrivacyMode.LOCAL_NORMALIZED:
            return _type_token(value)
        return "sha256:" + _hash(value)

    def serialize_for_postgres(self, evidence: Any) -> str:
        """Return safe JSON-shaped evidence suitable for PostgreSQL persistence."""
        return json.dumps(self.protect(evidence), sort_keys=True, separators=(",", ":"))

    def for_log(self, evidence: Any) -> Any:
        """Return a safe log payload without mutating caller-owned evidence."""
        return self.protect(evidence)

    def sanitize_prompt_text(self, prompt: str) -> str:
        """Remove common free-text literal forms before an Ollama request is captured."""
        replacement = "<literal>" if self.mode is PrivacyMode.LOCAL_NORMALIZED else "sha256:<redacted>"
        sanitized = _EMAIL.sub(replacement, prompt)
        sanitized = _UUID.sub(replacement, sanitized)
        sanitized = _IDENTIFIER.sub(replacement, sanitized)
        return _QUOTED.sub(replacement, sanitized)


def _type_token(value: Any) -> str:
    if isinstance(value, str):
        return "<string>"
    if isinstance(value, int):
        return "<integer>"
    if isinstance(value, float):
        return "<number>"
    return "<" + type(value).__name__ + ">"


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
