#!/usr/bin/env python3
"""Generate a 32-byte control-plane master key for a mounted secret file."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from secrets import token_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Mounted-secret file path")
    arguments = parser.parse_args()
    output: Path = arguments.output
    if not output.parent.is_dir():
        parser.error(
            f"Parent directory does not exist: {output.parent}. "
            "For local development, run 'mkdir -p .secrets' and use "
            "--output .secrets/control_plane_master_key. Docker mounts that file at "
            "/run/secrets/control_plane_master_key."
        )
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as key_file:
        key_file.write(token_bytes(32))
    print(f"Generated 32-byte control-plane master key at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
