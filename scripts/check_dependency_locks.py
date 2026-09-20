"""Verify direct pins and hashes in the authoritative Python lock contract."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")


def _pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if match := PIN.match(line):
            pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pins


def main() -> int:
    intent = _pins(ROOT / "requirements.in")
    production = _pins(ROOT / "requirements.production.in")
    lock_path = ROOT / "requirements.txt"
    lock_text = lock_path.read_text(encoding="utf-8")
    locked = _pins(lock_path)
    if not intent or any(locked.get(name) != version for name, version in intent.items()):
        raise RuntimeError("requirements.txt does not contain every exact direct dependency pin")
    if not production or any(
        intent.get(name) != version for name, version in production.items()
    ):
        raise RuntimeError("production roots must be an exact subset of direct dependency intent")
    stanzas = re.split(r"\n(?=[A-Za-z0-9_.-]+==)", lock_text)
    package_stanzas = [stanza for stanza in stanzas if PIN.match(stanza)]
    if not package_stanzas or any("--hash=sha256:" not in stanza for stanza in package_stanzas):
        raise RuntimeError("every locked Python dependency must carry a SHA-256 artifact hash")
    if '"lockfileVersion": 3' not in (ROOT / "frontend" / "package-lock.json").read_text(
        encoding="utf-8"
    ):
        raise RuntimeError("frontend package-lock.json v3 is required")
    print(
        "DEPENDENCY LOCK CHECK: PASS "
        f"({len(intent)} direct pins, {len(production)} production roots, "
        f"{len(package_stanzas)} locked Python packages)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
