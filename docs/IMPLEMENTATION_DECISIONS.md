# Implementation Decisions

This document records the fixed decisions in the master implementation plan; it introduces no alternatives.

- The development target is Intel x86_64 macOS, CPython 3.10.x, and linux/amd64 containers. The Python 3.10 compatibility overrides supersede earlier runtime references.
- Phase 0 verified macOS 15.7.7 on an Intel Core i7-8850H with 16 GiB RAM, CPython 3.10.20 in `nosql/`, Docker linux/amd64, and Ollama 0.32.9. Python must remain 3.10 and project packages must remain inside `nosql/`.
- `nosql/` is the sole normal-development Python virtual environment. Root `requirements.txt` is canonical and all direct dependencies are pinned.
- PostgreSQL 17 with pgvector is the control database. MongoDB is the optimized data platform and is accessed through typed adapters only.
- Ollama runs on the host and is CPU-only. Benchmarking and any AI inference are mutually exclusive through a global isolation lock.
- The lightweight Docker topology is the normal development environment. The paper topology is reserved for phases that explicitly require it.
- Node v25.2.1/npm 11.6.2 are observed host tools only. Node 22 LTS must be pinned before the frontend phase; do not change Node during pre-frontend work.
- The LLM has structured advisory and ranking roles only. It receives no database credentials or execution authority and cannot change safety thresholds.
- Evaluations happen in equivalent sandbox state. Deterministic statistics and safety policy admit or reject candidates.
- Production actions are typed, reversible, credential-isolated, ledgered, and retain configured human approval boundaries.
- Initial autonomous actions are limited to safe `CREATE_INDEX` and `SET_QUERY_SETTINGS_INDEX_HINT` variants under the stated constraints.
- Safety, data integrity, reversibility, non-regression evidence, and reproducibility override implementation convenience.
