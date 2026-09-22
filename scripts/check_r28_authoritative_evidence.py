#!/usr/bin/env python3
"""Fail-closed verification that authoritative R28 evidence is complete.

Checks the authoritative manifest, required constituents, true-JSONL raw
evidence, and per-dataset validation manifests.  Invalidated pre-fix evidence
is never counted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.evidence import is_valid_jsonl_file  # noqa: E402

EXPERIMENTS_DIR = ROOT / "artifacts/experiments"
MANIFEST = EXPERIMENTS_DIR / "R28_AUTHORITATIVE_MANIFEST.json"
MODES = (
    "B0_NATIVE",
    "B1_DETERMINISTIC_NO_GATE",
    "B2_LLM_RANK_NO_GATE",
    "B3_DETERMINISTIC_WITH_GATE",
    "B4_LLM_WITH_GATE",
    "B5_FULL_WITH_EXPERIENCE",
)
REQUIRED_KINDS = ("commercebench", "safetybench", "nosqlbench")


def fail(message: str) -> NoReturn:
    print("ERROR:", message, file=sys.stderr)
    sys.exit(1)


def main() -> int:
    if not MANIFEST.exists():
        fail("authoritative manifest is absent; run the orchestrator")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("status") != "PASSED":
        fail(f"authoritative manifest status is {manifest.get('status')!r}, not PASSED")
    constituents = manifest.get("constituents", [])
    present = {(item.get("kind"), item.get("profile"), item.get("mode")): item for item in constituents}
    for kind in REQUIRED_KINDS:
        if not any(item.get("kind") == kind and item.get("status") == "PASSED" for item in constituents):
            fail(f"required constituent kind {kind!r} has no PASSED evidence")
    for profile in ("standard", "publication"):
        for mode in MODES:
            item = present.get(("commercebench", profile, mode))
            if item is None or item.get("status") != "PASSED":
                fail(f"missing PASSED authoritative evidence for {profile}/{mode}")
            if profile == "publication" and not str(item.get("name", "")).startswith("commercebench-r28b-publication-"):
                fail(f"publication evidence for {mode} is not from the r28b optimized-reset generation")
            evidence = Path(item["evidence"])
            if not evidence.exists():
                fail(f"evidence path does not exist: {evidence}")
            if evidence.is_dir():
                pair_files = sorted((evidence / "pairs").glob("*.jsonl"))
                if not pair_files:
                    fail(f"publication evidence has no pair files: {evidence}")
                for pair_file in pair_files:
                    if not is_valid_jsonl_file(pair_file):
                        fail(f"evidence is not valid JSONL: {pair_file}")
                reset_manifest = evidence / "reset.json"
                if not reset_manifest.exists():
                    fail(f"publication evidence is missing reset implementation metadata: {evidence}")
                reset_document = json.loads(reset_manifest.read_text(encoding="utf-8"))
                if reset_document.get("reset_implementation") != "delta":
                    fail(f"publication evidence did not use the optimized delta reset: {evidence}")
            elif not is_valid_jsonl_file(evidence):
                fail(f"evidence is not valid JSONL: {evidence}")
            dataset_manifest = (evidence / "dataset.json") if evidence.is_dir() else evidence.with_suffix(".manifest.json")
            if not dataset_manifest.exists():
                fail(f"dataset validation manifest missing: {dataset_manifest}")
            document = json.loads(dataset_manifest.read_text(encoding="utf-8"))
            payload = document.get("dataset", document)
            for field in ("seed", "generator_version", "observed_collection_counts", "dataset_fingerprint", "workload_fingerprint"):
                if field not in payload:
                    fail(f"dataset manifest {dataset_manifest} is missing {field!r}")
    print("r28 authoritative evidence: complete and fail-closed verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
