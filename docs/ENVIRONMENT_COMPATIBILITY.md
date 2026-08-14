# Environment Compatibility

## Required development environment

- macOS on Intel x86_64
- CPython 3.10.x, with an x86_64 interpreter
- Project-local `nosql/` virtual environment
- Binary wheels for every pinned direct dependency
- Docker containers running linux/amd64
- Docker Desktop resources sufficient for the selected profile

## Host services

Ollama runs on the macOS host at `http://127.0.0.1:11434`; containers use `http://host.docker.internal:11434`. On macOS below 14, an existing working Ollama installation may be recorded but must not be upgraded automatically. An unavailable Ollama blocks AI integration phases, not early non-AI phases.

## Verification

Canonical local Python: CPython 3.10.x  
Canonical architecture: x86_64  
Canonical venv: `<repo-root>/nosql`  
Canonical dependency source: `<repo-root>/requirements.txt`

## Observed development machine values

Collected during the current Phase 0 run:

- Host OS: macOS 15.7.7 (build 24G720)
- Host architecture: x86_64
- CPU: Intel(R) Core(TM) i7-8850H CPU @ 2.60GHz; AVX available; 6 physical cores / 12 logical CPUs; 16 GiB RAM
- Python: CPython 3.10.20 at `/usr/local/opt/python@3.10/bin/python3.10`, x86_64
- Virtual environment: `<repo-root>/nosql`; its interpreter is CPython 3.10.20 x86_64
- pip: 26.2.1 in `nosql`
- Docker CLI: 29.6.1; Docker Compose: v5.3.0; x86_64/linux-amd64 execution verified
- Ollama: 0.32.9 and host API available
- MongoDB CPU compatibility: PASS

Installed direct dependency versions match every Phase 0 pin: FastAPI 0.112.2, Pydantic 2.8.2 / pydantic-core 2.20.1, SQLAlchemy 2.0.32, asyncpg 0.30.0, PyMongo 4.13.2, NumPy 1.26.4, SciPy 1.12.0, cryptography 42.0.8, and the remaining packages in `requirements.txt`. `pip check` and the required import smoke test pass.

Phase 0 passed on the actual Intel Mac environment using `make phase0-acceptance`.

## Frontend runtime policy

The current host exposes Node v25.2.1 and npm 11.6.2. These are not canonical project frontend runtimes. Before Phase 27 (Frontend Foundation), the project must pin and use Node 22 LTS and record the actual selected version here. Do not change Node during pre-frontend phases.

## Intel benchmark isolation and development topology

Ollama inference and embedding must never overlap controlled MongoDB benchmark measurement windows on this CPU-only Intel Mac. The lightweight Docker development topology is the normal environment; do not start the paper/reproduction topology during ordinary development unless its phase explicitly requires it.

Run `./scripts/bootstrap.sh` for the complete Phase 0 verification sequence. Dependency changes require the reproduction, wheel check, clean `nosql/` recreation, import verification, `pip check`, and documentation of the deliberate change here.
