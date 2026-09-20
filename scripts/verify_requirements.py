#!/usr/bin/env python3
"""Verify the compatibility-critical Phase 0 package pins."""

from __future__ import annotations

import importlib.metadata
import platform
import sys


REQUIRED_PINS = {
    "fastapi": "0.133.0",
    "starlette": "1.3.1",
    "uvicorn": "0.30.6",
    "pydantic": "2.8.2",
    "pydantic-core": "2.20.1",
    "pydantic-settings": "2.4.0",
    "email-validator": "2.2.0",
    "SQLAlchemy": "2.0.32",
    "alembic": "1.13.2",
    "asyncpg": "0.30.0",
    "pgvector": "0.3.2",
    "pymongo": "4.13.2",
    "dnspython": "2.6.1",
    "httpx": "0.27.2",
    "numpy": "1.26.4",
    "scipy": "1.12.0",
    "cryptography": "50.0.0",
    "argon2-cffi": "23.1.0",
    "PyJWT": "2.13.0",
    "tenacity": "9.0.0",
    "structlog": "24.4.0",
    "prometheus-client": "0.20.0",
    "pytest": "9.0.3",
    "pytest-asyncio": "1.3.0",
    "pytest-cov": "5.0.0",
    "ruff": "0.6.9",
    "mypy": "1.11.2",
    "pip-audit": "2.9.0",
}


def main() -> int:
    failed = sys.version_info[:2] != (3, 12) or platform.machine() != "x86_64"
    print(f"Python: {platform.python_version()} (required 3.12.x)")
    print(f"Architecture: {platform.machine()} (required x86_64)")
    for package, expected in REQUIRED_PINS.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            print(f"{package}: MISSING (expected {expected})", file=sys.stderr)
            failed = True
            continue
        status = "PASS" if actual == expected else "FAIL"
        print(f"{package}: {actual} (expected {expected}) {status}")
        failed = failed or actual != expected
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
