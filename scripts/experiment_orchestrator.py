#!/usr/bin/env python3
"""Resumable, fail-closed R28 experiment orchestrator.

Each constituent (CommerceBench experiment, SafetyBench, NoSQLBench) has an
explicit durable state (PENDING/RUNNING/PASSED/FAILED/INVALID).  A nonzero
return code is never recorded as success, and a required constituent failure
fails the whole orchestration.

Authoritative reruns use new ``r28a`` experiment IDs; invalidated evidence
from earlier runs is never treated as complete and is never overwritten.

Usage:
  ./nosql/bin/python scripts/experiment_orchestrator.py \
      --mongo-uri "mongodb://..." --run-standard --run-publication \
      --run-safetybench --run-nosqlbench
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from benchmarks.orchestration import (  # noqa: E402
    Constituent,
    ConstituentState,
    authoritative_python,
    discard_secret_dir,
    disposable_secret_dir,
    is_authoritative_pass,
    overall_status,
    provision_bench_environment,
    read_json,
    run_command,
    utc_now,
    write_json,
)

EXPERIMENTS_DIR = Path("artifacts/experiments")
AUTHORITATIVE_MANIFEST = EXPERIMENTS_DIR / "R28_AUTHORITATIVE_MANIFEST.json"
MODES = (
    "B0_NATIVE",
    "B1_DETERMINISTIC_NO_GATE",
    "B2_LLM_RANK_NO_GATE",
    "B3_DETERMINISTIC_WITH_GATE",
    "B4_LLM_WITH_GATE",
    "B5_FULL_WITH_EXPERIENCE",
)

# STANDARD/SafetyBench/NoSQLBench remain the accepted r28a generation.  The
# PUBLICATION reset implementation changed, so authoritative publication runs
# use a new r28b generation and never reuse r28a publication pairs.
GENERATION_BY_PROFILE = {"standard": "r28a", "publication": "r28b"}
SUPERSEDED_PUBLICATION_PREFIX = "commercebench-r28a-publication-"


def experiment_name(profile: str, mode: str) -> str:
    generation = GENERATION_BY_PROFILE.get(profile, "r28a")
    return f"commercebench-{generation}-{profile}-{mode.lower()}"


def _commercebench_evidence(profile: str, name: str) -> Path:
    if profile == "publication":
        return EXPERIMENTS_DIR / name
    return EXPERIMENTS_DIR / f"{name}-trials.jsonl"


def _finish(constituent: Constituent, rc: int | None, stdout: str, stderr: str, evidence: Path, *, evidence_present: bool | None = None) -> Constituent:
    constituent.returncode = rc
    constituent.stdout_log = str(EXPERIMENTS_DIR / f"{constituent.name}.stdout.log")
    constituent.stderr_log = str(EXPERIMENTS_DIR / f"{constituent.name}.stderr.log")
    Path(constituent.stdout_log).write_text(stdout, encoding="utf-8")
    Path(constituent.stderr_log).write_text(stderr, encoding="utf-8")
    constituent.finished_at = utc_now()
    present = evidence.exists() if evidence_present is None else evidence_present
    from benchmarks.orchestration import status_for_returncode

    constituent.status = status_for_returncode(rc, evidence_present=present)
    if constituent.status is not ConstituentState.PASSED:
        constituent.failure_reason = f"returncode={rc}; evidence_present={present}"
    return constituent


def run_commercebench(profile: str, mode: str, mongo_uri: str, python: str, *, force: bool = False) -> Constituent:
    name = experiment_name(profile, mode)
    evidence = _commercebench_evidence(profile, name)
    manifest_path = EXPERIMENTS_DIR / f"{name}.json"
    constituent = Constituent(
        name=name,
        kind="commercebench",
        command=(
            python,
            "scripts/run_commercebench_profile.py",
            "--profile",
            profile,
            "--mode",
            mode,
            "--uri",
            mongo_uri,
            "--output",
            str(evidence),
            "--pair-id",
            name,
        ),
        evidence=str(evidence),
        profile=profile,
        mode=mode,
    )
    if manifest_path.exists() and not force:
        manifest = read_json(manifest_path)
        if is_authoritative_pass(manifest):
            constituent.status = ConstituentState.PASSED
            constituent.returncode = 0
            started = manifest.get("started_at")
            finished = manifest.get("finished_at")
            constituent.started_at = started if isinstance(started, str) else None
            constituent.finished_at = finished if isinstance(finished, str) else None
            return constituent
    constituent.status = ConstituentState.RUNNING
    constituent.started_at = utc_now()
    write_json(manifest_path, constituent.to_dict())
    rc, out, err = run_command(constituent.command)
    _finish(constituent, rc, out, err, evidence)
    write_json(manifest_path, constituent.to_dict())
    return constituent


def run_safetybench(python: str, *, force: bool = False) -> Constituent:
    name = "safetybench-r28a"
    evidence = EXPERIMENTS_DIR / f"{name}.json"
    constituent = Constituent(
        name=name,
        kind="safetybench",
        command=(python, "-m", "pytest", "backend/tests/safetybench"),
        evidence=str(evidence),
    )
    if evidence.exists() and not force:
        manifest = read_json(evidence)
        if is_authoritative_pass(manifest):
            constituent.status = ConstituentState.PASSED
            constituent.returncode = 0
            return constituent
    constituent.status = ConstituentState.RUNNING
    constituent.started_at = utc_now()
    rc, out, err = run_command(constituent.command)
    _finish(constituent, rc, out, err, evidence, evidence_present=True)
    write_json(evidence, constituent.to_dict())
    return constituent


def run_nosqlbench(*, force: bool = False) -> Constituent:
    name = "nosqlbench-r28a"
    evidence = EXPERIMENTS_DIR / f"{name}.json"
    constituent = Constituent(
        name=name,
        kind="nosqlbench",
        command=("docker", "compose", "--profile", "bench", "run", "--rm", "nosqlbench-smoke"),
        evidence=str(evidence),
    )
    if evidence.exists() and not force:
        manifest = read_json(evidence)
        if is_authoritative_pass(manifest):
            constituent.status = ConstituentState.PASSED
            constituent.returncode = 0
            return constituent
    secret_dir = disposable_secret_dir()
    try:
        environment = provision_bench_environment(secret_dir=secret_dir)
        constituent.status = ConstituentState.RUNNING
        constituent.started_at = utc_now()
        rc, out, err = run_command(constituent.command, environment=environment)
    except RuntimeError as error:
        constituent.status = ConstituentState.FAILED
        constituent.failure_reason = str(error)
        constituent.finished_at = utc_now()
        write_json(evidence, constituent.to_dict())
        discard_secret_dir(secret_dir)
        return constituent
    _finish(constituent, rc, out, err, evidence, evidence_present=True)
    write_json(evidence, constituent.to_dict())
    discard_secret_dir(secret_dir)
    return constituent


def _load_existing() -> dict[str, Constituent]:
    """Load previously recorded authoritative constituents so re-invocations merge."""
    if not AUTHORITATIVE_MANIFEST.exists():
        return {}
    try:
        document = read_json(AUTHORITATIVE_MANIFEST)
    except (ValueError, OSError):
        return {}
    existing: dict[str, Constituent] = {}
    raw = document.get("constituents")
    if not isinstance(raw, list):
        return existing
    for payload in raw:
        if isinstance(payload, dict):
            constituent = Constituent.from_dict(payload)
            existing[constituent.name] = constituent
    return existing


def orchestrate(args: argparse.Namespace, profiles: Sequence[str]) -> int:
    python = authoritative_python(ROOT)
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    merged = _load_existing()
    for superseded in [name for name in merged if name.startswith(SUPERSEDED_PUBLICATION_PREFIX)]:
        merged.pop(superseded)
    for profile in profiles:
        for mode in MODES:
            name = experiment_name(profile, mode)
            if name not in merged:
                merged[name] = Constituent(name=name, kind="commercebench", profile=profile, mode=mode, status=ConstituentState.PENDING)
    if args.run_safetybench and "safetybench-r28a" not in merged:
        merged["safetybench-r28a"] = Constituent(name="safetybench-r28a", kind="safetybench", status=ConstituentState.PENDING)
    if args.run_nosqlbench and "nosqlbench-r28a" not in merged:
        merged["nosqlbench-r28a"] = Constituent(name="nosqlbench-r28a", kind="nosqlbench", status=ConstituentState.PENDING)
    _persist(merged)
    for profile in profiles:
        for mode in MODES:
            constituent = run_commercebench(profile, mode, args.mongo_uri, python, force=args.force)
            merged[constituent.name] = constituent
            _persist(merged)
    if args.run_safetybench:
        constituent = run_safetybench(python, force=args.force)
        merged[constituent.name] = constituent
        _persist(merged)
    if args.run_nosqlbench:
        constituent = run_nosqlbench(force=args.force)
        merged[constituent.name] = constituent
        _persist(merged)
    constituents = list(merged.values())
    status = overall_status(constituents)
    write_json(
        AUTHORITATIVE_MANIFEST,
        {
            "generated_at": utc_now(),
            "profiles": list(profiles),
            "modes": list(MODES),
            "status": status.value,
            "constituents": [item.to_dict() for item in constituents],
        },
    )
    print(f"overall_status={status.value}")
    return 0 if status is ConstituentState.PASSED else 1


def _persist(constituents: Sequence[Constituent] | dict[str, Constituent]) -> None:
    values = list(constituents.values()) if isinstance(constituents, dict) else list(constituents)
    write_json(
        AUTHORITATIVE_MANIFEST,
        {
            "generated_at": utc_now(),
            "status": overall_status(values).value,
            "constituents": [item.to_dict() for item in values],
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-uri", required=True)
    parser.add_argument("--run-standard", action="store_true")
    parser.add_argument("--run-publication", action="store_true")
    parser.add_argument("--run-safetybench", action="store_true")
    parser.add_argument("--run-nosqlbench", action="store_true")
    parser.add_argument("--force", action="store_true", help="Rerun even previously PASSED constituents")
    args = parser.parse_args()
    profiles: list[str] = []
    if args.run_standard:
        profiles.append("standard")
    if args.run_publication:
        profiles.append("publication")
    if not profiles and not args.run_safetybench and not args.run_nosqlbench:
        print("No constituents selected; nothing to run")
        return 2
    return orchestrate(args, profiles)


if __name__ == "__main__":
    raise SystemExit(main())
