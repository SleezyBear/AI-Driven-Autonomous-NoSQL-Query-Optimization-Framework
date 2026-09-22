#!/usr/bin/env python3
"""Invalidate (never delete) the correct-but-slow r28a PUBLICATION evidence.

The r28a publication measurements are methodologically valid but were produced
with the slow full-restore reset.  They are superseded by an equivalent faster
reset and are classified ``INVALID_SUPERSEDED_RESET_IMPLEMENTATION`` so they can
never be mixed with the r28b authoritative run.  Raw pair files, manifests,
logs and hashes are preserved.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS_DIR = ROOT / "artifacts/experiments"
INDEX = EXPERIMENTS_DIR / "R28_SUPERSEDED_PUBLICATION_EVIDENCE.json"
AUTHORITATIVE_MANIFEST = EXPERIMENTS_DIR / "R28_AUTHORITATIVE_MANIFEST.json"
CLASSIFICATION = "INVALID_SUPERSEDED_RESET_IMPLEMENTATION"
REASON = "superseded_by_verified_equivalent_faster_reset"
PREFIX = "commercebench-r28a-publication-"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(directory: Path) -> dict[str, str]:
    return {str(path.relative_to(directory)): sha256(path) for path in sorted(directory.rglob("*")) if path.is_file()}


def invalidate() -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for manifest_path in sorted(EXPERIMENTS_DIR.glob(f"{PREFIX}b*.json")):
        name = manifest_path.stem
        backup = manifest_path.with_suffix(".pre-supersession.json")
        if not backup.exists():
            shutil.copy2(manifest_path, backup)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["original_status"] = manifest.get("status")
        manifest["status"] = "INVALID"
        manifest["classification"] = CLASSIFICATION
        manifest["invalid_reasons"] = [REASON]
        manifest["superseded_at"] = now()
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        directory = EXPERIMENTS_DIR / name
        hashes: dict[str, str] = {}
        if directory.exists():
            hashes = inventory(directory)
            marker = directory / "SUPERSEDED.json"
            marker.write_text(
                json.dumps({"classification": CLASSIFICATION, "invalid_reasons": [REASON], "superseded_at": now(), "hashes": hashes}, indent=2) + "\n",
                encoding="utf-8",
            )
        entries.append({"experiment_id": name, "manifest": str(manifest_path), "backup": str(backup), "hashes": hashes})
    document = {
        "classification": CLASSIFICATION,
        "invalid_reasons": [REASON],
        "superseded_at": now(),
        "raw_evidence_preserved": True,
        "authoritative_replacement_prefix": "commercebench-r28b-publication-",
        "superseded_experiments": entries,
    }
    INDEX.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    _mark_top_manifest()
    return entries


def _mark_top_manifest() -> None:
    if not AUTHORITATIVE_MANIFEST.exists():
        return
    try:
        manifest = json.loads(AUTHORITATIVE_MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    for constituent in manifest.get("constituents", []):
        name = str(constituent.get("name", ""))
        if name.startswith(PREFIX):
            constituent["classification"] = CLASSIFICATION
    AUTHORITATIVE_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    entries = invalidate()
    print(f"superseded_publication_experiments={len(entries)}")
    for entry in entries:
        hashes = entry["hashes"]
        count = len(hashes) if isinstance(hashes, dict) else 0
        print(f"  {entry['experiment_id']} ({count} files hashed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
