"""Review tracked and non-ignored secret candidates without printing values."""

from __future__ import annotations

import math
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
ASSIGNMENT = re.compile(
    r'''(?im)^\s*[A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|SIGNING_KEY|MASTER_KEY)\s*[:=]\s*["']([^"']+)["']'''
)
YAML_ASSIGNMENT = re.compile(
    r"(?im)^\s*[A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|SIGNING_KEY|MASTER_KEY)\s*:\s*([^\s#]+)"
)
URI_CREDENTIAL = re.compile(r"(?:mongodb(?:\+srv)?|postgres(?:ql)?(?:\+asyncpg)?)://[^\s:@]+:([^\s@]+)@")
PUBLIC_MARKERS = ("dev_only", "test", "example", "replace-with", "dummy", "opaque")
SENSITIVE_FILENAMES = {".env", "control_plane_master_key", "mongodb_replica_keyfile"}


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    return -sum((count / len(value)) * math.log2(count / len(value)) for count in counts.values())


def _classification(path: str, value: str) -> str:
    lowered = value.lower()
    if path == ".env.example":
        return "EXAMPLE_ONLY"
    if path == "Makefile" or path.startswith("backend/tests/") or path.startswith("scripts/"):
        return "TEST_DUMMY"
    if path in {"docker-compose.yml", "docker-compose.paper.yml"}:
        return "EXAMPLE_ONLY"
    if any(marker in lowered for marker in PUBLIC_MARKERS):
        return "EXAMPLE_ONLY"
    return "REAL_SECRET" if len(value) >= 20 and _entropy(value) >= 3.5 else "FALSE_POSITIVE"


def main() -> int:
    """Classify repository candidates and fail closed on any likely real secret."""
    tracked = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    findings: Counter[str] = Counter()
    real_paths: list[str] = []
    for relative_path in tracked:
        path = ROOT / relative_path
        if path.name in SENSITIVE_FILENAMES or relative_path.startswith("nosql/"):
            findings["REAL_SECRET"] += 1
            real_paths.append(relative_path)
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if PRIVATE_KEY.search(content):
            findings["REAL_SECRET"] += 1
            real_paths.append(relative_path)
        for match in (
            *ASSIGNMENT.findall(content),
            *YAML_ASSIGNMENT.findall(content),
            *URI_CREDENTIAL.findall(content),
        ):
            classification = _classification(relative_path, match.strip("'\""))
            findings[classification] += 1
            if classification == "REAL_SECRET":
                real_paths.append(relative_path)
    for classification in ("FALSE_POSITIVE", "TEST_DUMMY", "EXAMPLE_ONLY", "REAL_SECRET"):
        print(f"{classification}: {findings[classification]}")
    if real_paths:
        print("TRACKED SECRET AUDIT: FAIL")
        for path in sorted(set(real_paths)):
            print(f"candidate path requiring rotation/review: {path}", file=sys.stderr)
        return 1
    print("TRACKED SECRET AUDIT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
