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
| 20–56 | Not started | Not started | Defined in master implementation plan |

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
