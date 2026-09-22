#!/usr/bin/env python3
"""Generate JSONL/CSV/Parquet exports from raw and authoritative trial evidence.

Reads true JSON Lines (or whole-file JSON objects/arrays) and writes
``artifacts/exports/<stem>.jsonl``, ``.csv``, and ``.parquet`` when pyarrow is
available.  JSON-array files are re-emitted as true JSONL, never labelled as
JSONL without conversion.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "artifacts/raw"
EXPERIMENTS_DIR = ROOT / "artifacts/experiments"
OUT_DIR = ROOT / "artifacts/exports"
INVALID_CLASSIFICATION = "INVALID_NONAUTHORITATIVE_R28_RUN"


def load_records(path: Path) -> list[dict[str, Any]]:
    """Load a source as records, converting arrays/objects to record lists."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl" and not text.lstrip().startswith("["):
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        parsed = json.loads(text)
        records = parsed if isinstance(parsed, list) else [parsed]
    return [record for record in records if isinstance(record, dict)]


def write_exports(source: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    stem = source.stem
    keys = sorted({key for record in records for key in record})
    with (OUT_DIR / f"{stem}.jsonl").open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    with (OUT_DIR / f"{stem}.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=keys, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({key: json.dumps(record.get(key), default=str) if isinstance(record.get(key), (dict, list)) else record.get(key) for key in keys})
    try:
        import pyarrow as pa  # type: ignore[import-not-found]
        import pyarrow.parquet as pq  # type: ignore[import-not-found]
    except ImportError:
        print(f"pyarrow unavailable; skipped Parquet for {source.name}")
        return
    pq.write_table(pa.Table.from_pylist(records), OUT_DIR / f"{stem}.parquet")


def authoritative_sources() -> list[Path]:
    manifest_path = EXPERIMENTS_DIR / "R28_AUTHORITATIVE_MANIFEST.json"
    if not manifest_path.exists():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources: list[Path] = []
    for constituent in manifest.get("constituents", []):
        if constituent.get("classification") == INVALID_CLASSIFICATION or constituent.get("status") != "PASSED":
            continue
        if constituent.get("kind") != "commercebench":
            continue
        evidence = Path(constituent["evidence"])
        if evidence.is_dir():
            sources.extend(sorted((evidence / "pairs").glob("*.jsonl")))
        elif evidence.exists():
            sources.append(evidence)
    return sources


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sources = authoritative_sources()
    if not sources and RAW_DIR.exists():
        sources = sorted(list(RAW_DIR.glob("*.jsonl")) + list(RAW_DIR.glob("*.json")))
    if not sources:
        print("no raw or authoritative evidence found; nothing to export")
        return 2
    exported = 0
    for source in sources:
        try:
            records = load_records(source)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            print(f"skipping unparseable evidence {source}: {error}")
            continue
        write_exports(source, records)
        exported += 1
    print(f"generate_exports: wrote exports for {exported} sources into {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
