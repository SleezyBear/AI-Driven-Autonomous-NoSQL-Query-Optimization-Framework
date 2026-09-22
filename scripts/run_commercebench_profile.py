#!/usr/bin/env python3
"""Run CommerceBench for a profile and ablation mode and persist raw evidence.

SMOKE and STANDARD run one AB/BA pair.  PUBLICATION runs the frozen sampling
protocol: 12 A/A calibration pairs, 15-40 required candidate pairs, and the
frozen admission gate, with 60-second warmup and 120-second measurement
windows (seconds, never operation counts).

Usage:
  ./nosql/bin/python scripts/run_commercebench_profile.py \
      --profile publication --mode B4_LLM_WITH_GATE \
      --uri "mongodb://..." --output artifacts/experiments/<id>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.ablations.experiments import AblationMode  # noqa: E402
from benchmarks.commercebench import WorkloadProfile  # noqa: E402
from benchmarks.r28_runner import build_settings, run_publication, run_single_pair  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "standard", "publication"), required=True)
    parser.add_argument("--mode", choices=tuple(mode.value for mode in AblationMode), default=AblationMode.B0_NATIVE.value)
    parser.add_argument("--uri", required=True)
    parser.add_argument("--output", type=Path, required=True, help="Evidence file (SMOKE/STANDARD) or directory (PUBLICATION)")
    parser.add_argument("--pair-id", type=str, default=None)
    parser.add_argument("--warmup-ops", type=int, default=None)
    parser.add_argument("--measurement-ops", type=int, default=None)
    parser.add_argument("--warmup-seconds", type=float, default=None)
    parser.add_argument("--measurement-seconds", type=float, default=None)
    return parser.parse_args()


def profile_enum(profile: str) -> WorkloadProfile:
    return WorkloadProfile(profile)


def main() -> int:
    args = parse_args()
    profile = profile_enum(args.profile)
    mode = AblationMode(args.mode)
    if profile is WorkloadProfile.PUBLICATION:
        prefix = args.pair_id or f"r28a-publication-{mode.value.lower()}"
        summary = run_publication(profile, mode, args.uri, args.output, prefix=prefix)
        print(f"evidence={args.output}")
        print(f"sampling_status={summary.get('sampling_status')}")
        print(f"admission={summary.get('admission')}")
        return 0
    pair_id = args.pair_id or f"r28a-{args.profile}-{mode.value.lower()}"
    settings = build_settings(
        profile,
        warmup_operations=args.warmup_ops,
        measurement_operations=args.measurement_ops,
        warmup_seconds=args.warmup_seconds,
        measurement_seconds=args.measurement_seconds,
    )
    run_single_pair(profile, mode, args.uri, args.output, pair_id=pair_id, settings=settings)
    print(f"evidence={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
