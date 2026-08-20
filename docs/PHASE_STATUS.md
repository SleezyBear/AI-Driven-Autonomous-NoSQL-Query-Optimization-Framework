# Phase Status

| Phase | Scope | Status | Observable test |
| --- | --- | --- | --- |
| 0 | Machine and dependency compatibility | COMPLETE — PASS | `make phase0-acceptance` |
| 1 | Backend skeleton | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests`; `./nosql/bin/ruff check backend`; `./nosql/bin/mypy backend/app`; `curl http://localhost:8000/health/live` |
| 2 | Container infrastructure | COMPLETE — PASS | `docker compose --profile light up -d`; `docker compose --profile light ps` |
| 3 | Control database | COMPLETE — PASS | `alembic upgrade`; `alembic downgrade`; `alembic upgrade` |
| 4 | Secret storage | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/security` |
| 5 | Auth and RBAC | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/auth` |
| 6 | Database adapter interface | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/adapters` |
| 7 | MongoDB capabilities | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/mongodb` |
| 8 | MongoDB permission boundary | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/mongodb` |
| 9 | Telemetry abstraction | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/telemetry` |
| 10 | Query shape registry | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/query_shapes` |
| 11 | Metrics collection | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/metrics` |
| 12 | Workload snapshots | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/workloads` |
| 13 | CommerceBench | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/commercebench` |
| 14 | Benchmark runner | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/benchmarks` |
| 15 | Statistical engine | COMPLETE — PASS | `make phase15-acceptance` |
| 16 | Safety policy | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/unit/admission/test_policy.py` |
| 17 | Append-only ledger | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/ledger` |
| 18 | Typed action schemas | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/actions` |
| 19 | Deterministic index generator | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/candidates` |
| 20 | Sandbox index evaluation | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/evaluation` |
| 21 | Ollama provider | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/ai` |
| 22 | Benchmark/Ollama isolation | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/isolation` |
| 23 | Experience memory | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/experience` |
| 24 | Complete diagnosis pipeline | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/pipeline` |
| 25 | Optimization state machine | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/state_machine` |
| 26 | Durable worker | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/worker` |
| 27 | Frontend foundation | COMPLETE — PASS | `docker compose --profile light build frontend` and Node 22 Vitest |
| 28 | Target dashboard | COMPLETE — PASS | Node 22 Vitest and `http://localhost:5173` |
| 29 | Workload dashboard | COMPLETE — PASS | Node 22 Vitest and `http://localhost:5173` |
| 30 | Run dashboard | COMPLETE — PASS | Node 22 Vitest and `http://localhost:5173/runs` |
| 31 | Approval flow | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/approvals` |
| 32 | Production executor | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/production` |
| 33 | Owned index rollback | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/rollback` |
| 34 | Post-deployment monitoring | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/monitoring` |
| 35 | Query-settings index hints | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/production/test_query_settings.py` |
| 36 | Workload shift detection | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/monitoring` |
| 37 | Query rewrite recommendations | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/recommendations` |
| 38 | Index cleanup advisor | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/recommendations` |
| 39 | Configuration advisor | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/recommendations` |
| 40 | Privacy modes | COMPLETE — PASS | `./nosql/bin/python -m pytest backend/tests/security backend/tests/ai` |
| 41–56 | Not started | Not started | Defined in master implementation plan |

Phase progression is strictly one phase at a time: implement, run its test and prior tests, fix regressions, then update this document.

## Phase 0 record

- Result: PASS
- Verification command: `make phase0-acceptance`
- Verified host: macOS 15.7.7; Intel Core i7-8850H; x86_64; 16 GiB RAM
- Verified Python: CPython 3.10.20 in `<repo-root>/nosql`
- Verified containers: Docker x86_64 with linux/amd64 execution
- Verified Ollama: 0.32.9

## Phase 1 record

- Result: PASS
- Verification: 2 endpoint tests passed; Ruff and mypy passed; `GET /health/live` returned `{"status":"alive"}`.

## Phase 2 record

- Result: PASS
- Verification: PostgreSQL, monitored MongoDB, evaluation MongoDB, API, worker, and frontend were healthy in the light profile.
- Replica-set verification: monitored `rs-monitored`; evaluation `rs-evaluation`.
- API readiness: `GET /health/ready` returned `{"status":"ready"}`.

## Phase 3 record

- Result: PASS
- Verification: migration `0001_control_plane_schema` completed up → down → up against PostgreSQL 17.
- pgvector extension is enabled and all 26 required control-plane tables are present.

## Phase 4 record

- Result: PASS
- AES-256-GCM uses a file-only 32-byte master key at `/run/secrets/control_plane_master_key`.
- Every ciphertext has a random 12-byte nonce and authenticates secret ID, target ID, secret type, and key version as AAD.
- Tests prove plaintext is absent from ciphertext and altered AAD prevents decryption.
- Local development uses the gitignored `.secrets/control_plane_master_key` staging file, mounted by Docker Compose at `/run/secrets/control_plane_master_key`; the key never enters `.env` or PostgreSQL.
- Mount verification passed for both API and worker containers.

## Phase 5 record

- Result: PASS
- Roles: VIEWER, OPERATOR, APPROVER, and ADMIN.
- Password hashes use Argon2 and authenticated principals use signed JWTs.
- Unauthorized operations return HTTP 403; self-approval is rejected even when the actor otherwise has approval authority.

## Phase 6 record

- Result: PASS
- Core orchestration receives only typed namespace and index metadata operations through `DatabaseAdapter`.
- `FakeDatabaseAdapter` and `MongoDBAdapter` both pass the shared contract suite.
- No arbitrary database-command execution method exists.

## Phase 7 record

- Result: PASS
- PyMongo `AsyncMongoClient` collected the MongoDB 8 server version, FCV, replica-set topology, query-settings/query-stats support, profiler status, and credential permission roles from the monitored local instance.
- Host-local testing uses `directConnection=true` because the one-member Docker replica set advertises its internal service hostname.

## Phase 8 record

- Result: PASS
- Separate MongoDB observer and executor credentials are initialized in the light development topology.
- The executor can perform metadata/index operations but is denied insert, update, replace, delete, collection drop, and database drop operations.
- MongoDB authorization with replica sets uses a locally generated, gitignored internal key file that is copied with owner-only permissions inside each container.

## Phase 9 record

- Result: PASS
- Provider preference is `$queryStats` → diagnostic logs → existing profiler → current operations.
- Profiler availability is inspected using `profile: -1`; no provider enables profiling.

## Phase 10 record

- Result: PASS
- Server-provided `queryShapeHash` is preferred whenever available.
- Local fallback canonicalization replaces all predicate values with type tokens before persistence and SHA-256 hashing.

## Phase 11 record

- Result: PASS
- A real monitored-MongoDB read workload produced nonempty p50, p95, p99, and read-throughput measurements.
- Snapshots also capture resource, replication, scan, lock, error, and timeout fields without enabling profiler collection.

## Phase 12 record

- Result: PASS
- Immutable snapshots capture operation mix, query-shape and execution-time shares, global metrics, critical shapes, and an environment fingerprint.
- Protection includes explicitly affected and manually critical shapes, plus every shape at or above 1% of operations or execution time; the 90/9/1 acceptance distribution protects all three.

## Phase 13 record

- Result: PASS
- CommerceBench produces deterministic `customers`, `products`, `orders`, `events`, and `inventory` datasets from seed 42 for the smoke, standard, and publication profiles.
- Two resets of the same profile produce exactly matching dataset fingerprints.

## Phase 14 record

- Result: PASS
- Every paired comparison restores the requested snapshot before each arm, yielding the required restore → baseline → restore → candidate sequence.
- Each persisted arm record includes seed, dataset and initial-state fingerprints, environment fingerprint, metrics, arm, and pair ID; the acceptance test proves matching initial fingerprints.

## Phase 15 record

- Result: PASS
- Pre-Phase-15 audit: PASS; details and concrete evidence are in `docs/PRE_PHASE15_AUDIT.md`.
- `make phase15-acceptance` passed all 13 statistical unit tests and reported every required synthetic verdict.
- Full regression: 45 backend tests passed; Ruff, mypy, `pip check`, tracked-secret audit, and `make phase0-acceptance` passed.

## Phase 16 record

- Result: PASS
- The frozen safety policy is loaded from `backend/app/admission/default_policy.json`; it carries relative, absolute, hard-boundary, and headroom limits separately from zero-tolerance invariants.
- Phase acceptance: 16 admission-policy tests passed; full regression reached 48 backend tests with Ruff, mypy, and preflight passing.

## Phase 17 record

- Result: PASS
- Each append-only entry records before, intended, and after state; forward and inverse actions; evidence hash; actor; and previous/current SHA-256 ledger hashes.
- The chain verification test detects altered recorded state. Full regression reached 50 backend tests with Ruff, mypy, and preflight passing.

## Phase 18 record

- Result: PASS
- `CREATE_INDEX` and `SET_QUERY_SETTINGS_INDEX_HINT` are frozen typed schemas with exact typed inverse actions.
- Autonomous index validation rejects unique, TTL, sparse, partial, text, wildcard, geo, hashed, non-B-tree, and more-than-five-field variants. Full regression reached 61 backend tests with Ruff, mypy, and preflight passing.

## Phase 19 record

- Result: PASS
- MongoDB `find` candidates use only Equality → Sort → Range, Equality → Range → Sort, and Equality → Sort patterns, in deterministic order with SHA-256 fingerprints.
- Candidates are de-duplicated, schema-valid, and capped at five fields and five candidates per query shape. Full regression reached 64 backend tests with Ruff, mypy, and preflight passing.

## Phase 20 record

- Result: PASS
- Sandbox evaluation performs copy → verify → apply → benchmark → admission → cleanup only through the evaluation adapter; identical target IDs or topology identities are rejected before candidate application.
- Resource-budget violations are rejected, cleanup runs after benchmark failure, and tests prove the monitored adapter remains unchanged. Full regression reached 68 backend tests with Ruff, mypy, and preflight passing.

## Phase 21 record

- Result: PASS
- `AIProvider` has structured-only `diagnose`, `rank_candidates`, `explain_decision`, and `embed_experience` methods; `OllamaAIProvider` uses temperature 0 and retries malformed structured output exactly once.
- `FakeAIProvider` supports deterministic offline tests, and no provider exposes database execution authority. Full regression reached 71 backend tests with Ruff, mypy, and preflight passing.

## Phase 22 record

- Result: PASS
- A shared async lock serializes controlled benchmark measurement windows and Ollama generation/embedding requests on the Intel development machine.
- Both wait-order tests pass: Ollama waits for a benchmark, and a benchmark waits for active Ollama inference. Full regression reached 73 backend tests with Ruff, mypy, and preflight passing.

## Phase 23 record

- Result: PASS
- Experience records use EmbeddingGemma-compatible 768-dimensional vectors, with pgvector-backed PostgreSQL columns added by migration `0002_experience_memory_pgvector`.
- Memory can only reprioritize existing candidates; disabling it changes ranking at most and leaves deterministic admission unchanged. Full regression reached 75 backend tests with Ruff, mypy, and preflight passing.

## Phase 24 record

- Result: PASS
- The pipeline performs snapshot → deterministic evidence → deterministic candidate generation → experience retrieval → LLM diagnosis → LLM ranking → sandbox evaluation → deterministic admission.
- Only known deterministic candidates reach sandbox evaluation, and the initial evaluation set is capped at three. Full regression reached 76 backend tests with Ruff, mypy, and preflight passing.

## Phase 25 record

- Result: PASS
- The explicit optimization lifecycle contains every specified state, including deployment, monitoring, rollback, rollback-blocked, and failed terminal outcomes.
- Only declared transitions are permitted; invalid transitions raise without changing the current state or its history. Full regression reached 80 backend tests with Ruff, mypy, and preflight passing.

## Phase 26 record

- Result: PASS
- PostgreSQL jobs use `FOR UPDATE SKIP LOCKED` claims, leases, heartbeats, and owner-guarded completion; an expired lease can be recovered after worker failure.
- Two concurrent workers completed 100 jobs exactly once. Migration `0003_durable_worker_jobs` is applied to the local development database; full regression reached 82 backend tests with Ruff, mypy, and preflight passing.

## Phase 27 record

- Result: PASS
- The frontend foundation uses React 18, TypeScript, Vite 5, React Router, TanStack Query, Tailwind, shadcn/ui configuration, Recharts, Vitest, and Playwright dependencies under `frontend/package.json`.
- The project is pinned to Node 22.14.0 and npm 10 inside the linux/amd64 Docker build and `.nvmrc`; the host Node 25 installation remains unchanged. The Docker production build and local Vitest suite pass; backend regression remains 82 passing tests.

## Phase 28 record

- Result: PASS
- The target dashboard displays health, version, topology, capabilities, telemetry source, namespace allowlist, deployment mode, evaluation target, and autonomy eligibility for the local monitored MongoDB target.
- Expert Mode exposes the low-level evidence below every field. Node 22 Vitest reports two passing test files; the rebuilt dashboard is healthy at `http://localhost:5173`, and backend regression remains 82 passing tests.

## Phase 29 record

- Result: PASS
- The workload dashboard displays throughput, read/write split, p50/p95/p99, query-shape distribution, CPU, memory, disk, and replication lag.
- No workload telemetry window has been captured, so values truthfully report absent observations rather than synthetic metrics. Expert Mode reveals the associated normalized empty evidence. Node 22 Vitest reports three passing test files and backend regression remains 82 passing tests.

## Phase 30 record

- Result: PASS
- The run dashboard displays diagnosis, candidates, AI ranking, evaluation, statistical verdict, safety verdict, approval, deployment, post-deployment result, and rollback status as one full decision trail.
- No run has been selected, so the dashboard records the absent evidence truthfully rather than fabricating a decision. Expert Mode exposes every evidence state. Node 22 Vitest reports four passing test files and backend regression remains 82 passing tests.

## Phase 31 record

- Result: PASS
- Semi-autonomous actions require human approval bound immutably to their action ID and evidence hash.
- A changed evidence hash marks the prior approval stale and fails closed before deployment authorization. Focused approval tests pass; full regression reached 85 backend tests with Ruff, mypy, and preflight passing.

## Phase 32 record

- Result: PASS
- The restricted executor locks its target; verifies admitted production eligibility, evidence-bound approval, and current state; records `PREPARED`; executes only a typed `CREATE_INDEX`; verifies resulting state; records `APPLIED`; and unlocks in all cases.
- Raw actions, stale approval, unadmitted actions, state drift, and pre-existing indexes fail before target modification. Focused production tests pass; full regression reached 90 backend tests with Ruff, mypy, and preflight passing.

## Phase 33 record

- Result: PASS
- Index rollback requires an `APPLIED` optimizer ledger entry with matching target, namespace, exact index specification/fingerprint, and current state without relevant drift.
- Any failed ownership check returns `ROLLBACK_BLOCKED` without mutation. Tests cover both a successful exact owned rollback and drift rejection; full regression reached 92 backend tests with Ruff, mypy, and preflight passing.

## Phase 34 record

- Result: PASS
- Monitoring windows retain latency, throughput, resource, error, timeout, replication, and literal-free workload-distribution evidence.
- Workload shifts are explicitly marked and withhold causal attribution. A catastrophic regression invokes the ownership-verified rollback path even when a workload shift is present.
- Focused monitoring tests pass; full regression reached 95 backend tests with Ruff, mypy, dependency preflight, and whitespace validation passing.

## Phase 35 record

- Result: PASS
- The typed query-settings boundary exposes only `allowedIndexes`; it cannot express `reject` or `queryFramework`. Every referenced index must already exist.
- An existing query setting always requires current evidence-bound human approval before replacement. Rollback verifies ownership and unchanged current state, then restores the exact prior allowed-index state (including absence).
- Focused production tests pass; full regression reached 99 backend tests with Ruff, mypy, dependency preflight, and whitespace validation passing.

## Phase 36 record

- Result: PASS
- Workload-shape distributions use total variation distance over their union with the fixed `0.20` threshold. A shift is admitted only after three consecutive threshold breaches.
- A sustained shift requests re-analysis once per shift episode and exposes no production-mutation capability. A non-shift window resets the sequence.
- Focused monitoring tests pass; full regression reached 102 backend tests with Ruff, mypy, dependency preflight, and whitespace validation passing.

## Phase 37 record

- Result: PASS
- Query rewrites are recommendation-only and have no execution or production-mutation capability.
- Sandbox equivalence checks count, document identity, canonical document hashes, and ordering whenever ordering is semantically required. Any mismatch returns `REJECTED_SAFETY_INVARIANT`.
- Focused recommendation tests pass; full regression reached 105 backend tests with Ruff, mypy, dependency preflight, and whitespace validation passing.

## Phase 38 record

- Result: PASS
- The cleanup advisor detects unused, duplicate, redundant-prefix, and stale optimizer-owned indexes from literal-free metadata and observed-use evidence.
- It is recommendation-only: primary-key indexes are excluded and neither human-created nor optimizer-owned indexes can be dropped by this phase.
- Focused recommendation tests pass; full regression reached 108 backend tests with Ruff, mypy, dependency preflight, and whitespace validation passing.

## Phase 39 record

- Result: PASS
- Configuration recommendations are restricted to the frozen, known control-plane whitelist and always require separate human approval; this phase contains no apply capability.
- Unknown LLM parameter names, out-of-range values, and any candidate that weakens security, durability, consistency, or data integrity are rejected.
- Focused recommendation tests pass; full regression reached 111 backend tests with Ruff, mypy, dependency preflight, and whitespace validation passing.

## Phase 40 record

- Result: PASS
- `LOCAL_NORMALIZED` retains only value type tokens, while `STRICT_HASHED` retains deterministic SHA-256 representations. Both preserve structure without retaining literals.
- The privacy boundary protects log payloads, PostgreSQL evidence serialization, and captured Ollama prompt/embed requests. Tests prove known email and identifier values are absent from all three.
- Focused privacy and AI tests pass; full regression reached 114 backend tests with Ruff, mypy, dependency preflight, and whitespace validation passing.
