"""Strict raw-evidence readers used by R28 reproduction and acceptance checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read true JSON Lines, rejecting a JSON array or non-object line."""
    records: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8")
    if text.lstrip().startswith("["):
        raise ValueError(f"{path} is a JSON array, not JSON Lines")
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number} is not a JSON object")
        records.append(value)
    return records


def is_valid_jsonl_file(path: Path) -> bool:
    """Whether a file is parseable as one JSON object per line."""
    try:
        read_jsonl(path)
    except (ValueError, json.JSONDecodeError):
        return False
    return True
