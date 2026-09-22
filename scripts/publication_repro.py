#!/usr/bin/env python3
"""Regenerate R28 aggregates, tables, and figures from raw authoritative evidence.

This corrupts no raw evidence and reruns no expensive experiment.  It fails
closed when authoritative evidence is missing, when a JSONL file is not valid
JSONL, or when only invalidated evidence is present.
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.evidence import read_jsonl  # noqa: E402

EXPERIMENTS_DIR = ROOT / "artifacts/experiments"
RAW_DIR = ROOT / "artifacts/raw"
OUT_DIR = ROOT / "artifacts/repro"
TABLES_DIR = OUT_DIR / "tables"
FIGURES_DIR = OUT_DIR / "figures"
INVALID_CLASSIFICATION = "INVALID_NONAUTHORITATIVE_R28_RUN"


def fail(message: str, code: int = 2) -> None:
    print("ERROR:", message, file=sys.stderr)
    sys.exit(code)


def discover_authoritative_experiments() -> list[dict[str, Any]]:
    manifest_path = EXPERIMENTS_DIR / "R28_AUTHORITATIVE_MANIFEST.json"
    if not manifest_path.exists():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    discovered: list[dict[str, Any]] = []
    for constituent in manifest.get("constituents", []):
        if constituent.get("kind") != "commercebench":
            continue
        if constituent.get("status") != "PASSED" or constituent.get("classification") == INVALID_CLASSIFICATION:
            continue
        evidence = Path(constituent["evidence"])
        if not evidence.exists():
            continue
        discovered.append(constituent)
    return discovered


def _p99(record: dict[str, Any]) -> float | None:
    measurement = record.get("measurement", {})
    value = measurement.get("p99_latency_ms")
    return None if value is None else float(value)


def summarize_publication(directory: Path) -> dict[str, Any]:
    pairs = sorted((directory / "pairs").glob("*.jsonl"))
    baseline_values: list[float] = []
    candidate_values: list[float] = []
    throughputs: list[float] = []
    for pair_file in pairs:
        for record in read_jsonl(pair_file):
            value = _p99(record)
            if value is None:
                continue
            throughput = record.get("measurement", {}).get("throughput_successful_ops_per_second")
            if record.get("arm") == "baseline":
                baseline_values.append(value)
            elif record.get("arm") == "candidate":
                candidate_values.append(value)
            if throughput is not None:
                throughputs.append(float(throughput))
    admission_path = directory / "admission.json"
    admission = json.loads(admission_path.read_text(encoding="utf-8")) if admission_path.exists() else {}
    summary = {
        "pair_files": len(pairs),
        "baseline_p99_ms": statistics.fmean(baseline_values) if baseline_values else None,
        "candidate_p99_ms": statistics.fmean(candidate_values) if candidate_values else None,
        "throughput_ops_s": statistics.fmean(throughputs) if throughputs else None,
        "admission_status": admission.get("status"),
        "required_pair_count": admission.get("required_pair_count"),
        "actual_pair_count": admission.get("actual_pair_count"),
    }
    if summary["baseline_p99_ms"] and summary["candidate_p99_ms"]:
        summary["p99_change_fraction"] = (summary["candidate_p99_ms"] - summary["baseline_p99_ms"]) / summary["baseline_p99_ms"]
    else:
        summary["p99_change_fraction"] = None
    return summary


def summarize_single_pair(evidence: Path) -> dict[str, Any]:
    records = read_jsonl(evidence)
    baseline = next((item for item in records if item.get("arm") == "baseline"), None)
    candidate = next((item for item in records if item.get("arm") == "candidate"), None)
    baseline_p99 = _p99(baseline) if baseline else None
    candidate_p99 = _p99(candidate) if candidate else None
    return {
        "pair_files": 1,
        "baseline_p99_ms": baseline_p99,
        "candidate_p99_ms": candidate_p99,
        "throughput_ops_s": (baseline or {}).get("measurement", {}).get("throughput_successful_ops_per_second"),
        "admission_status": None,
        "required_pair_count": None,
        "actual_pair_count": None,
        "p99_change_fraction": ((candidate_p99 - baseline_p99) / baseline_p99) if baseline_p99 and candidate_p99 else None,
    }


def aggregate(experiments: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for constituent in experiments:
        evidence = Path(constituent["evidence"])
        if evidence.is_dir():
            summary = summarize_publication(evidence)
        elif evidence.exists():
            summary = summarize_single_pair(evidence)
        else:
            continue
        summary.update({"experiment_id": constituent["name"], "profile": constituent.get("profile"), "mode": constituent.get("mode")})
        rows.append(summary)
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "experiment_count": len(rows), "experiments": rows}


def write_tables(aggregate_doc: dict[str, Any]) -> None:
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    rows = aggregate_doc["experiments"]
    headers = ["experiment_id", "profile", "mode", "pair_files", "baseline_p99_ms", "candidate_p99_ms", "p99_change_fraction", "throughput_ops_s", "admission_status", "required_pair_count", "actual_pair_count"]
    with (TABLES_DIR / "experiments.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_figure(aggregate_doc: dict[str, Any]) -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    rows = [row for row in aggregate_doc["experiments"] if row.get("p99_change_fraction") is not None]
    width, height, margin = 900, 60 + 40 * max(len(rows), 1), 220
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<text x="20" y="30" font-family="monospace" font-size="16">R28 p99 latency change (candidate vs baseline)</text>',
    ]
    for index, row in enumerate(rows):
        y = 60 + index * 40
        change = float(row["p99_change_fraction"])
        bar = max(min(abs(change), 1.0), 0.0) * 500
        color = "#2e7d32" if change <= 0 else "#c62828"
        parts.append(f'<text x="20" y="{y + 14}" font-family="monospace" font-size="12">{row["experiment_id"]}</text>')
        parts.append(f'<rect x="{margin}" y="{y}" width="{bar:.1f}" height="20" fill="{color}"/>')
        parts.append(f'<text x="{margin + bar + 8:.1f}" y="{y + 14}" font-family="monospace" font-size="12">{change:+.3%}</text>')
    parts.append("</svg>")
    (FIGURES_DIR / "p99_change.svg").write_text("\n".join(parts) + "\n", encoding="utf-8")


def main() -> int:
    experiments = discover_authoritative_experiments()
    if not experiments:
        fail("no authoritative R28 CommerceBench evidence found; run the orchestrator first")
    for constituent in experiments:
        evidence = Path(constituent["evidence"])
        files = sorted(evidence.glob("pairs/*.jsonl")) if evidence.is_dir() else [evidence]
        for file in files:
            if file.suffix == ".jsonl" and file.exists():
                read_jsonl(file)
    aggregate_doc = aggregate(experiments)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "aggregates.json").write_text(json.dumps(aggregate_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_tables(aggregate_doc)
    write_figure(aggregate_doc)
    (OUT_DIR / "README.md").write_text(
        "# R28 reproduction outputs\n\n"
        "Regenerated from raw authoritative evidence in `artifacts/experiments/`. "
        "`aggregates.json` holds per-experiment aggregates, `tables/experiments.csv` the "
        "publication table, and `figures/p99_change.svg` the p99 change figure.\n",
        encoding="utf-8",
    )
    print(f"publication_repro: wrote aggregates/tables/figures for {aggregate_doc['experiment_count']} experiments")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001 - explicit fail-closed entrypoint
        fail(f"unhandled exception: {error}")
