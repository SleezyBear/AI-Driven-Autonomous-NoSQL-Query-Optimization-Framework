#!/usr/bin/env python3
"""Fail if core orchestration imports the MongoDB driver directly."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend/app"
# Direct driver access is permitted only in narrow MongoDB implementation
# boundaries.  The evaluation copier is deliberately one of those boundaries:
# it copies a physical MongoDB evaluation target and is not portable orchestration.
MONGODB_SPECIFIC_DIRECTORIES = (APP / "mongodb", APP / "evaluation")


def imports_pymongo(path: Path) -> bool:
    """Inspect import declarations without importing application modules."""
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "pymongo" or alias.name.startswith("pymongo.") for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom) and node.module and (node.module == "pymongo" or node.module.startswith("pymongo.")):
            return True
    return False


def main() -> int:
    violations = [
        path.relative_to(ROOT)
        for path in APP.rglob("*.py")
        if not any(directory in path.parents for directory in MONGODB_SPECIFIC_DIRECTORIES)
        and imports_pymongo(path)
    ]
    if violations:
        raise SystemExit("pymongo is limited to MongoDB-specific modules: " + ", ".join(str(path) for path in violations))
    print("Database portability import boundary: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
