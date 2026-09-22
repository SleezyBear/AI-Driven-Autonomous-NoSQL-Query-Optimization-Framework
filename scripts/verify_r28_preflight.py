#!/usr/bin/env python3
"""Lightweight R28 preflight audit and durable handoff writer.

Checks that the corrected R28 scaffolding exists, reports the authoritative
evidence status, and writes docs/R28_EXECUTION_HANDOFF.md so runs may be
resumed.  Runs no expensive benchmarks.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PATHS = [
    ROOT / "benchmarks/commercebench/dataset.py",
    ROOT / "benchmarks/commercebench/validation.py",
    ROOT / "benchmarks/ablations.py",
    ROOT / "benchmarks/r28_runner.py",
    ROOT / "benchmarks/publication.py",
    ROOT / "scripts/run_commercebench_profile.py",
    ROOT / "artifacts/experiments",
    ROOT / "artifacts/raw",
    ROOT / "artifacts/generated",
]
HANDOFF_PATH = ROOT / "docs/R28_EXECUTION_HANDOFF.md"
AUTHORITATIVE_MANIFEST = ROOT / "artifacts/experiments/R28_AUTHORITATIVE_MANIFEST.json"
INVALID_INDEX = ROOT / "artifacts/experiments/R28_INVALID_EVIDENCE.json"


def human_readable_bytes(n: int) -> str:
    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if abs(n) < 1024.0:
            return f"{n:3.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PiB"


def run_audit() -> dict[str, object]:
    present = [str(path.relative_to(ROOT)) for path in REQUIRED_PATHS if path.exists()]
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED_PATHS if not path.exists()]
    usage = shutil.disk_usage(ROOT)
    return {
        "present": present,
        "missing": missing,
        "disk_free": human_readable_bytes(usage.free),
        "authoritative_status": _authoritative_status(),
        "invalidated_count": _invalidated_count(),
        "constituents": _constituents(),
    }


def _constituents() -> list[str]:
    if not AUTHORITATIVE_MANIFEST.exists():
        return []
    try:
        document = json.loads(AUTHORITATIVE_MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    lines: list[str] = []
    for item in document.get("constituents", []):
        if not isinstance(item, dict):
            continue
        lines.append(f"- {item.get('name')}: {item.get('status')} (rc={item.get('returncode')})")
    return lines


def _authoritative_status() -> str:
    if not AUTHORITATIVE_MANIFEST.exists():
        return "ABSENT"
    try:
        return str(json.loads(AUTHORITATIVE_MANIFEST.read_text(encoding="utf-8")).get("status", "UNKNOWN"))
    except json.JSONDecodeError:
        return "UNREADABLE"


def _invalidated_count() -> int:
    if not INVALID_INDEX.exists():
        return 0
    try:
        return len(json.loads(INVALID_INDEX.read_text(encoding="utf-8")).get("invalidated_experiments", []))
    except json.JSONDecodeError:
        return 0


def write_handoff(audit: dict[str, object]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "# R28 Execution Handoff\n",
        f"generated_at: {now}\n\n",
        "## Audit summary\n",
        f"- authoritative_status: {audit['authoritative_status']}\n",
        f"- invalidated_legacy_runs: {audit['invalidated_count']}\n",
        f"- disk_free: {audit['disk_free']}\n\n",
        "## Present scaffolding\n",
    ]
    lines.extend(f"- {path}\n" for path in audit["present"])  # type: ignore[union-attr]
    lines.append("\n## Missing scaffolding\n")
    lines.extend(f"- {path}\n" for path in audit["missing"])  # type: ignore[union-attr]
    lines.append("\n## Authoritative constituents\n")
    constituents = audit["constituents"]
    lines.extend(f"{line}\n" for line in constituents)  # type: ignore[union-attr]
    if not constituents:
        lines.append("- (none recorded yet)\n")
    lines.extend(
        [
            "\n## Resume policy\n",
            "- Heavy experiments run sequentially; PUBLICATION modes never run concurrently.\n",
            "- Resume from the first non-PASSED authoritative experiment; never rerun a PASSED one without cause.\n",
            "- Authoritative IDs use the `commercebench-r28a-` prefix; pre-fix evidence is INVALID and is never counted.\n",
            "- Use `./nosql/bin/python` for all authoritative Python execution.\n",
            "\n## Next commands\n",
            "- ./nosql/bin/python scripts/experiment_orchestrator.py --mongo-uri <uri> --run-safetybench --run-nosqlbench --run-standard --run-publication\n",
            "- make publication-repro\n",
            "- make r28-acceptance\n",
        ]
    )
    HANDOFF_PATH.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    audit = run_audit()
    write_handoff(audit)
    print("R28 preflight audit:")
    print(f"  authoritative_status={audit['authoritative_status']} invalidated={audit['invalidated_count']} disk_free={audit['disk_free']}")
    if audit["missing"]:
        print("  missing scaffolding:")
        for path in audit["missing"]:  # type: ignore[union-attr]
            print(f"    {path}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
