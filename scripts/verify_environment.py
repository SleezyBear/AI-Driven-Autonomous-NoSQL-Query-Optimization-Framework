#!/usr/bin/env python3
"""Collect and verify the Intel macOS Phase 0 development environment."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = REPO_ROOT / "nosql" / "bin" / "python"


def command(*args: str) -> tuple[int, str]:
    executable = shutil.which(args[0])
    if executable is None:
        return 127, "unavailable"
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    return result.returncode, (result.stdout or result.stderr).strip()


def report(label: str, passed: bool, detail: str) -> bool:
    print(f"{label:<30} {'PASS' if passed else 'FAIL':<4} {detail}")
    return passed


def macos_value(*args: str) -> str:
    _, value = command(*args)
    return value


def cpu_compatible(features: str, brand: str) -> bool:
    normalized = features.upper()
    has_avx = "AVX1.0" in normalized or " AVX" in normalized
    normalized_brand = brand.upper()
    if "CORE(TM)2" in normalized_brand or "CORE 2" in normalized_brand:
        return False
    model = re.search(r"I[357]-(\d{4,5})", normalized_brand)
    if model is not None and int(model.group(1)[:1]) < 4:
        return False
    return has_avx


def main() -> int:
    success = True
    system = platform.system()
    is_macos = system == "Darwin"
    success &= report("macOS", is_macos, macos_value("sw_vers", "-productVersion") if is_macos else system)

    machine = platform.machine()
    success &= report("Intel x86_64", machine == "x86_64", machine)

    brand = macos_value("sysctl", "-n", "machdep.cpu.brand_string") if is_macos else "unavailable"
    features = macos_value("sysctl", "-n", "machdep.cpu.features") if is_macos else "unavailable"
    mongo_ok = is_macos and machine == "x86_64" and cpu_compatible(features, brand)
    success &= report("MongoDB CPU requirements", mongo_ok, f"CPU={brand}; AVX={'yes' if 'AVX' in features.upper() else 'no'}")

    py_version = platform.python_version()
    py_ok = sys.version_info[:2] == (3, 10) and platform.python_implementation() == "CPython"
    success &= report("CPython 3.10", py_ok, py_version)
    success &= report("Python x86_64", platform.machine() == "x86_64", platform.machine())
    in_venv = sys.prefix != sys.base_prefix
    expected_venv = Path(sys.executable).resolve() == VENV_PYTHON.resolve() if VENV_PYTHON.exists() else False
    success &= report("nosql virtual environment", in_venv and expected_venv, sys.executable)

    print("\nHOST DETAILS")
    print(f"macOS build: {macos_value('sw_vers', '-buildVersion') if is_macos else 'unavailable'}")
    print(f"CPU model: {brand}")
    print(f"CPU feature flags: {features}")
    for label, key in (("Physical cores", "hw.physicalcpu"), ("Logical CPUs", "hw.logicalcpu"), ("RAM bytes", "hw.memsize")):
        print(f"{label}: {macos_value('sysctl', '-n', key) if is_macos else 'unavailable'}")
    usage = shutil.disk_usage(REPO_ROOT)
    print(f"Free disk bytes: {usage.free}")
    print(f"Python executable: {sys.executable}")
    print(f"Virtual environment path: {VENV_PYTHON}")
    _, pip_version = command(sys.executable, "-m", "pip", "--version")
    print(f"pip version: {pip_version}")

    docker_code, docker_version = command("docker", "--version")
    docker_ok = docker_code == 0
    success &= report("Docker available", docker_ok, docker_version)
    docker_status_code, docker_status = command("docker", "info", "--format", "{{.ServerVersion}} {{.Architecture}}")
    docker_running = docker_status_code == 0
    success &= report("Docker status", docker_running, docker_status)
    if docker_running:
        _, docker_arch = command("docker", "run", "--rm", "alpine", "uname", "-m")
        success &= report("Docker linux/amd64", docker_arch == "x86_64", docker_arch)
    else:
        success &= report("Docker linux/amd64", False, "Docker daemon unavailable")
    _, compose_version = command("docker", "compose", "version")
    print(f"Docker Compose version: {compose_version}")

    ollama_code, ollama_version = command("ollama", "--version")
    ollama_http_code, ollama_http = command("curl", "--fail", "--silent", "http://localhost:11434/api/version")
    ollama_ok = ollama_code == 0 and ollama_http_code == 0
    print(f"Ollama host: {'PASS' if ollama_ok else 'WARN'} {ollama_version if ollama_code == 0 else ollama_http}")
    _, node_version = command("node", "--version")
    _, npm_version = command("npm", "--version")
    print(f"Node version: {node_version}")
    print(f"npm version: {npm_version}")
    print(f"MongoDB CPU compatibility: {'PASS' if mongo_ok else 'FAIL'}")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
