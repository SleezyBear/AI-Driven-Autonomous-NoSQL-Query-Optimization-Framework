#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV_BIN="${UV_BIN:-$REPO_ROOT/.tools/uv/uv}"
if [[ ! -x "$UV_BIN" ]]; then
  UV_BIN="$(command -v uv || true)"
fi
VENV_PYTHON="$REPO_ROOT/nosql/bin/python"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "FAIL: Phase 0 requires macOS."
  exit 1
fi
if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "FAIL: Phase 0 requires Intel x86_64."
  exit 1
fi
if [[ ! -x "$UV_BIN" ]]; then
  echo "Project-local uv is not available at $UV_BIN."
  echo "R1 requires uv-managed CPython 3.12 without changing system Python."
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
if [[ -x "$VENV_PYTHON" ]] && [[ "$($VENV_PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" != "3.12" ]]; then
  echo "Replacing project-owned nosql environment created with the wrong Python version."
  rm -rf "$REPO_ROOT/nosql"
fi
if [[ ! -x "$VENV_PYTHON" ]]; then
  "$UV_BIN" venv --python 3.12 --seed "$REPO_ROOT/nosql"
fi
if [[ "$($VENV_PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" != "3.12" ]]; then
  echo "FAIL: nosql virtual environment must use CPython 3.12.x."
  exit 1
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
