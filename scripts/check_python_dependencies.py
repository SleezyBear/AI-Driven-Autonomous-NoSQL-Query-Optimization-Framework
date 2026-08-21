#!/usr/bin/env python3
"""Import Phase 0 dependencies and report their installed versions."""

from __future__ import annotations

import importlib.metadata
import platform
import sys


PACKAGES = (
    "fastapi",
    "uvicorn",
    "pydantic",
    "pydantic-settings",
    "SQLAlchemy",
    "alembic",
    "asyncpg",
    "pgvector",
    "pymongo",
    "dnspython",
    "httpx",
    "numpy",
    "scipy",
    "cryptography",
    "argon2-cffi",
    "PyJWT",
    "tenacity",
    "structlog",
    "prometheus-client",
    "pytest",
)


def main() -> int:
    if sys.version_info[:2] != (3, 12):
        print("Dependency import failed: Python 3.12 is required.", file=sys.stderr)
        return 1
    if platform.machine() != "x86_64":
        print("Dependency import failed: x86_64 Python is required.", file=sys.stderr)
        return 1
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        import pydantic  # noqa: F401
        import pydantic_settings  # noqa: F401
        import sqlalchemy  # noqa: F401
        import alembic  # noqa: F401
        import asyncpg  # noqa: F401
        import pgvector  # noqa: F401
        import pymongo  # noqa: F401
        import dns  # noqa: F401
        import httpx  # noqa: F401
        import numpy  # noqa: F401
        import scipy  # noqa: F401
        import cryptography  # noqa: F401
        import argon2  # noqa: F401
        import jwt  # noqa: F401
        import tenacity  # noqa: F401
        import structlog  # noqa: F401
        import prometheus_client  # noqa: F401
        import pytest  # noqa: F401
    except ImportError as error:
        print(f"Dependency import failed: {error}", file=sys.stderr)
        return 1

    print(f"Python: {sys.version.split()[0]}")
    print(f"Architecture: {platform.machine()}")
    for package in PACKAGES:
        print(f"{package}: {importlib.metadata.version(package)}")
    print("DEPENDENCY IMPORT CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
