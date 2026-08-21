# Implementation Decisions

This document records the fixed decisions in the master implementation plan; it introduces no alternatives.

- The development target is Intel x86_64 macOS, uv-managed CPython 3.12.x in the project-local `nosql/` venv, and linux/amd64 containers. This does not alter the system/default Python installation.
- The historical Phase 0 environment used CPython 3.10.20. R1 supersedes that project runtime with isolated CPython 3.12.x while retaining all project packages inside `nosql/`.
- `nosql/` is the sole normal-development Python virtual environment. Root `requirements.txt` is canonical and all direct dependencies are pinned.
- PostgreSQL 17 with pgvector is the control database. MongoDB is the optimized data platform and is accessed through typed adapters only.
- Ollama runs on the host and is CPU-only. Benchmarking and any AI inference are mutually exclusive through a global isolation lock.
- The lightweight Docker topology is the normal development environment. The paper topology is reserved for phases that explicitly require it.
- Node v25.2.1/npm 11.6.2 remain observed host tools only. The project frontend is pinned to Node 22.14.0 via `.nvmrc`, `frontend/package.json`, and the linux/amd64 Node 22.14.0 Docker build image; no global Node installation was changed.
- The LLM has structured advisory and ranking roles only. It receives no database credentials or execution authority and cannot change safety thresholds.
- Evaluations happen in equivalent sandbox state. Deterministic statistics and safety policy admit or reject candidates.
- Production actions are typed, reversible, credential-isolated, ledgered, and retain configured human approval boundaries.
- Initial autonomous actions are limited to safe `CREATE_INDEX` and `SET_QUERY_SETTINGS_INDEX_HINT` variants under the stated constraints.
- Safety, data integrity, reversibility, non-regression evidence, and reproducibility override implementation convenience.
