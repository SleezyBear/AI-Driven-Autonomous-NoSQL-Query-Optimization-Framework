"""Generate deterministic CycloneDX inventories for backend and frontend."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "generated"


def _bom(name: str, components: list[dict[str, Any]], lock_bytes: bytes) -> dict[str, Any]:
    digest = hashlib.sha256(lock_bytes).hexdigest()
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}",
        "version": 1,
        "metadata": {
            "component": {"type": "application", "name": name, "version": "0.1.0"},
            "properties": [{"name": "dependency-lock-sha256", "value": digest}],
        },
        "components": sorted(components, key=lambda item: (str(item["name"]).lower(), item["version"])),
    }


def _backend() -> dict[str, Any]:
    requirements = (ROOT / "requirements.txt").read_bytes()
    roots = [
        line.split("==", 1)[0]
        for line in (ROOT / "requirements.production.in").read_text(
            encoding="utf-8"
        ).splitlines()
        if line and not line.startswith("#")
    ]
    pending = [canonicalize_name(name) for name in roots]
    distributions = {
        canonicalize_name(distribution.metadata["Name"]): distribution
        for distribution in importlib.metadata.distributions()
        if distribution.metadata.get("Name")
    }
    components: list[dict[str, Any]] = []
    included: set[str] = set()
    while pending:
        normalized = pending.pop()
        if normalized in included:
            continue
        try:
            distribution = distributions[normalized]
        except KeyError as error:
            raise RuntimeError(
                f"production SBOM dependency is not installed: {normalized}"
            ) from error
        included.add(normalized)
        name = distribution.metadata["Name"]
        components.append(
            {
                "type": "library",
                "name": name,
                "version": distribution.version,
                "purl": f"pkg:pypi/{normalized}@{distribution.version}",
                "scope": "required",
            }
        )
        for requirement_text in distribution.requires or ():
            requirement = Requirement(requirement_text)
            if requirement.marker is None or requirement.marker.evaluate():
                pending.append(canonicalize_name(requirement.name))
    return _bom("autonomous-nosql-optimizer-backend", components, requirements)


def _frontend() -> dict[str, Any]:
    lock_path = ROOT / "frontend" / "package-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    components = []
    for path, package in lock.get("packages", {}).items():
        if not path or package.get("dev") is True or "version" not in package:
            continue
        name = path.rsplit("node_modules/", 1)[-1]
        version = str(package["version"])
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:npm/{name.replace('/', '%2F')}@{version}",
                "scope": "required",
            }
        )
    return _bom("autonomous-nosql-optimizer-frontend", components, lock_path.read_bytes())


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for filename, document in (("backend.cdx.json", _backend()), ("frontend.cdx.json", _frontend())):
        (OUTPUT / filename).write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print("SBOM GENERATION: PASS (CycloneDX 1.5 backend/frontend)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
