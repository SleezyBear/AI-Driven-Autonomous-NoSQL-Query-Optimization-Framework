#!/usr/bin/env python3
"""Generate a MongoDB internal replica-set key file for local Docker development."""

from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path
from secrets import token_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Ignored local key-file path")
    arguments = parser.parse_args()
    output: Path = arguments.output
    if not output.parent.is_dir():
        parser.error(f"Parent directory does not exist: {output.parent}")

    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as key_file:
        key_file.write(base64.b64encode(token_bytes(768)))
    print(f"Generated MongoDB replica-set key file at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

