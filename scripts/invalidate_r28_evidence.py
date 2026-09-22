#!/usr/bin/env python3
"""Invalidate (never delete) non-authoritative pre-fix R28 CommerceBench runs.

The early R28 runs are preserved verbatim for audit but are explicitly marked
``INVALID_NONAUTHORITATIVE_R28_RUN`` so they can never be counted as
authoritative ablation/publication evidence.  Raw ``*-trials.jsonl`` evidence
is left untouched.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS_DIR = ROOT / "artifacts/experiments"
INVALID_INDEX = EXPERIMENTS_DIR / "R28_INVALID_EVIDENCE.json"
LEGACY_MANIFEST = EXPERIMENTS_DIR / "EXPERIMENTS_MANIFEST.json"
MANIFEST_BACKUP = EXPERIMENTS_DIR / "EXPERIMENTS_MANIFEST.pre-r28-invalidation.json"
CLASSIFICATION = "INVALID_NONAUTHORITATIVE_R28_RUN"
LEGACY_PATTERN = re.compile(r"^commercebench-(standard|publication)-b[0-5]_[a-z_]+\.json$")
REASONS = (
    "publication_seconds_treated_as_operation_counts",
    "b0_b5_behavioral_modes_not_wired",
    "required_aa_calibration_absent",
    "required_candidate_pair_sampling_absent",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def invalidate() -> list[str]:
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    invalidated: list[str] = []
    for manifest_path in sorted(EXPERIMENTS_DIR.glob("*.json")):
        if not LEGACY_PATTERN.match(manifest_path.name):
            continue
        backup = manifest_path.with_suffix(".pre-invalidation.json")
        if not backup.exists():
            shutil.copy2(manifest_path, backup)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["original_status"] = manifest.get("status")
        manifest["status"] = "INVALID"
        manifest["classification"] = CLASSIFICATION
        manifest["invalid_reasons"] = list(REASONS)
        manifest["invalidated_at"] = now()
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        invalidated.append(manifest_path.stem)
    if LEGACY_MANIFEST.exists():
        if not MANIFEST_BACKUP.exists():
            shutil.copy2(LEGACY_MANIFEST, MANIFEST_BACKUP)
        legacy = json.loads(LEGACY_MANIFEST.read_text(encoding="utf-8"))
        legacy["classification"] = CLASSIFICATION
        legacy["invalidated_at"] = now()
        legacy["invalid_reasons"] = list(REASONS)
        for entry in legacy.get("completed", []):
            entry["classification"] = CLASSIFICATION
        LEGACY_MANIFEST.write_text(json.dumps(legacy, indent=2) + "\n", encoding="utf-8")
    INVALID_INDEX.write_text(
        json.dumps(
            {
                "classification": CLASSIFICATION,
                "invalidated_at": now(),
                "reasons": list(REASONS),
                "invalidated_experiments": invalidated,
                "raw_evidence_preserved": True,
                "authoritative_replacement_prefix": "commercebench-r28a-",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return invalidated


def main() -> int:
    invalidated = invalidate()
    print(f"invalidated={len(invalidated)}")
    for name in invalidated:
        print(f"  {name}")
    if not invalidated:
        print("no legacy manifests matched; nothing to invalidate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
