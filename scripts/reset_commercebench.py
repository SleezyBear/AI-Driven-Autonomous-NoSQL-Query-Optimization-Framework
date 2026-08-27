"""Print a deterministic CommerceBench snapshot fingerprint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from benchmarks.commercebench import CommerceBench, WorkloadProfile  # noqa: E402


def main() -> int:
    """Generate the selected deterministic profile and print its reproducibility facts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=[profile.value for profile in WorkloadProfile], default="smoke")
    arguments = parser.parse_args()
    snapshot = CommerceBench().reset(WorkloadProfile(arguments.profile))
    print(f"profile={snapshot.profile.value}")
    print(f"seed={snapshot.seed}")
    print(f"generator_version={snapshot.generator_version}")
    print(f"collection_counts={snapshot.collection_counts}")
    print(f"fingerprint={snapshot.fingerprint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
