#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON310="$(command -v python3.10 || true)"
VENV_PYTHON="$REPO_ROOT/nosql/bin/python"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "FAIL: Phase 0 requires macOS."
  exit 1
fi
if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "FAIL: Phase 0 requires Intel x86_64."
  exit 1
fi
if [[ -z "$PYTHON310" ]]; then
  echo "Python 3.10 interpreter not found."
  echo "Phase 0 cannot continue until an x86_64 Python 3.10 interpreter is available."
  exit 1
fi
if [[ "$($PYTHON310 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" != "3.10" ]]; then
  echo "FAIL: python3.10 must be CPython 3.10.x."
  exit 1
fi
if [[ "$($PYTHON310 -c 'import platform; print(platform.machine())')" != "x86_64" ]]; then
  echo "FAIL: python3.10 is not x86_64."
  exit 1
fi

CPU_BRAND="$(sysctl -n machdep.cpu.brand_string)"
CPU_FEATURES="$(sysctl -n machdep.cpu.features)"
if [[ "$CPU_FEATURES" != *"AVX"* ]] || [[ "$CPU_BRAND" == *"Core(TM)2"* ]] || [[ "$CPU_BRAND" == *"Core 2"* ]] || [[ "$CPU_BRAND" =~ i[357]-[123][0-9]{3}([^0-9]|$) ]]; then
  echo "FAIL: MongoDB CPU compatibility check failed."
  exit 1
fi
echo "MongoDB CPU compatibility: PASS"

cd "$REPO_ROOT"
if [[ -x "$VENV_PYTHON" ]] && [[ "$($VENV_PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" != "3.10" ]]; then
  echo "Replacing project-owned nosql environment created with the wrong Python version."
  rm -rf "$REPO_ROOT/nosql"
fi
if [[ ! -x "$VENV_PYTHON" ]]; then
  "$PYTHON310" -m venv "$REPO_ROOT/nosql"
fi
if [[ "$($VENV_PYTHON -c 'import platform; print(platform.machine())')" != "x86_64" ]]; then
  echo "FAIL: nosql virtual environment Python is not x86_64."
  exit 1
fi

"$VENV_PYTHON" -m pip install --quiet --upgrade pip
rm -rf "$REPO_ROOT/.dependency-wheel-test"
mkdir -p "$REPO_ROOT/.dependency-wheel-test"
"$VENV_PYTHON" -m pip download --quiet --only-binary=:all: --dest "$REPO_ROOT/.dependency-wheel-test" -r "$REPO_ROOT/requirements.txt"
"$VENV_PYTHON" -m pip install --quiet -r "$REPO_ROOT/requirements.txt"
"$VENV_PYTHON" -m pip check
"$VENV_PYTHON" "$REPO_ROOT/scripts/check_python_dependencies.py"
"$VENV_PYTHON" "$REPO_ROOT/scripts/verify_requirements.py"
"$VENV_PYTHON" "$REPO_ROOT/scripts/verify_environment.py"

echo ""
echo "Next commands:"
echo "  source nosql/bin/activate"
echo "  make preflight"
echo "  make dev"
