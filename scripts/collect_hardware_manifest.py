"""Print the mandatory reproducibility manifest for the current benchmark host."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from benchmarks.hardware import SystemHardwareManifestCollector  # noqa: E402


def main() -> int:
    """Collect and print all hardware-manifest fields as stable JSON."""
    print(json.dumps(asdict(SystemHardwareManifestCollector().collect()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
