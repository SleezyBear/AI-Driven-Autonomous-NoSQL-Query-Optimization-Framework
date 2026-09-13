# Original Plan Compliance Matrix

This is an evidence-based classification of the original implementation plan.
It deliberately does not derive completion from `PHASE_STATUS.md`. The historical
test evidence is retained there; this matrix records whether the promised system
was actually implemented as of remediation R0.

## R19B corrective completion

R19B is **COMPLETE** as an integration-correctness slice: migration `0011` persists the
full lifecycle, enforces the sole initial `OPTIMIZATION` job through a PostgreSQL
partial unique index, and validates upgrade/downgrade safety on isolated disposable
databases. `make r19b-acceptance` passed with 233 backend tests, Ruff, mypy, and
`pip check`. R19 remains **INCOMPLETE** because the real worker service does not yet
claim and dispatch `OPTIMIZATION` jobs through the optimization workflow.

## R19C corrective completion

R19C is **COMPLETE** as durable worker infrastructure: `make r19c-acceptance`
passed with 19 focused worker tests, real PostgreSQL lease-expiry crash recovery,
idle and active-job graceful shutdown, PostgreSQL readiness/outage recovery,
Compose worker health/shutdown/restart verification, R19B regression, 250 backend
tests, Ruff, mypy, and `pip check`. The worker uses PostgreSQL claims, leases,
heartbeats, retry/backoff, and typed dispatch; it intentionally fails a
non-terminal `OPTIMIZATION` job as `ORCHESTRATION_UNAVAILABLE` instead of creating
fake lifecycle progress. Durable OptimizationRun orchestration is **NOT
IMPLEMENTED**, so R19 remains **INCOMPLETE**.

## R19D corrective boundary

R19D is **INCOMPLETE** and remains fail-closed at its persisted orchestration
boundary.
The component audit is recorded in `docs/R19D_COMPONENT_AUDIT.md`. Its
orchestrator prefix reloads persisted state, validates the active monitored
target, distinct active evaluation mapping, deployment mode, and sole
authoritative initial job, then lease-checks `CREATED → SNAPSHOTTING` and
returns the typed `WORKLOAD_SNAPSHOT_SERVICE_MISSING` blocker. Later R19E–K
components are real but intentionally remain unwired from this worker path.
R19 remains **INCOMPLETE**.

## R19E, R19F, and R19G–K corrective completion

R19E, R19F, and R19G–K are **COMPLETE** as integration-correctness slices.
Their acceptance chain verified durable literal-free workload evidence, grounded
diagnosis, deterministic immutable candidates, real Ollama ranking over opaque
handles, separate monitored/evaluation MongoDB trial persistence, frozen
statistical admission, and recovery/idempotency. The ordered real-AI gate passed
3 tests and `make r19gk-acceptance` completed with exit code 0; final backend
regression was 269 passed and 3 skipped, with Ruff, mypy (98 source files), and
`pip check` green. R19 remains **INCOMPLETE**: worker orchestration and the
excluded approval, deployment, monitoring, and rollback stages are not complete.

| Phase | Actual classification | Evidence observed | Material gap |
| --- | --- | --- | --- |
| 0 | PARTIAL | Host and dependency checks ran on the Intel Mac. | Historical Python 3.10 environment is superseded by R1’s Python 3.12 baseline. |
| 1 | PARTIAL | Backend package, health routes, lint and type checks exist. | Application paths remain largely scaffolded. |
| 2 | PARTIAL | Light Compose topology starts concrete PostgreSQL and MongoDB containers. | Production hardening and operational topology are absent. |
| 3 | SCAFFOLD_ONLY | Alembic migrations and a control-database boundary exist. | Relational schema is placeholder-level; R2 replaces it. |
| 4 | PARTIAL | File-backed master-key handling and tests exist. | No durable production secret lifecycle or rotation integration. |
| 5 | PARTIAL | RBAC models and unit tests exist. | No production identity/authentication integration. |
| 6 | PARTIAL | Adapter interfaces and test adapters exist. | Real adapters do not yet back the control-plane flow. |
| 7 | PARTIAL | MongoDB capability discovery was exercised against a container. | Snapshots are not durably integrated with target state. |
| 8 | PARTIAL | Permission-boundary tests exercise MongoDB roles. | Enforcement is not proven through the full production path. |
| 9 | PARTIAL | Telemetry abstractions and provider selection exist. | No durable real telemetry collection pipeline. |
| 10 | PARTIAL | Query-shape registry normalizes shapes. | Registry is in-memory rather than durable. |
| 11 | PARTIAL | Metric collection interfaces and tests exist. | Semantics and persistence do not meet the promised behavior. |
| 12 | PARTIAL | Snapshot objects are immutable in tests. | Snapshot lifecycle is not durably stored. |
| 13 | PARTIAL | Deterministic CommerceBench smoke data exists. | Benchmark dataset/workload is undersized and incomplete. |
| 14 | PARTIAL | Runner orchestration is testable. | It does not drive a real benchmark executor end-to-end. |
| 15 | PARTIAL | Statistical routines and acceptance tests exist. | Statistical defects identified by R14 remain. |
| 16 | PARTIAL | Safety-policy predicates exist. | No durable globally coordinated admission policy. |
| 17 | SCAFFOLD_ONLY | Ledger API and tests exist. | Ledger state is in-memory rather than append-only durable state. |
| 18 | PARTIAL | Typed action schemas exist. | They are not enforced through a durable deployment flow. |
| 19 | PARTIAL | Deterministic index candidates can be generated. | Candidates are not bound to real persisted evidence. |
| 20 | SCAFFOLD_ONLY | Sandbox interfaces and tests exist. | Evaluation is callback/fake based, not real isolated execution. |
| 21 | PARTIAL | Ollama/provider integration boundary exists. | Prompt and structured-output contracts are incomplete. |
| 22 | PARTIAL | Local isolation mechanisms are tested. | They are not proven around a real worker benchmark window. |
| 23 | SCAFFOLD_ONLY | Experience-memory API exists. | Repository is in-memory. |
| 24 | SCAFFOLD_ONLY | Pipeline stages and callbacks are represented. | There is no real persisted end-to-end pipeline. |
| 25 | PARTIAL | State-machine transitions are modeled and tested. | Transitions are not fully durable/idempotent workflow execution. |
| 26 | PARTIAL | Worker/job code and tests exist. | Jobs do not persist the complete real workflow. |
| 27 | PARTIAL | Docker-built React frontend foundation and tests exist. | It is not connected to a real control-plane API. |
| 28 | SCAFFOLD_ONLY | Target dashboard renders representative values. | Values are static rather than fetched from the API. |
| 29 | SCAFFOLD_ONLY | Workload dashboard renders representative values. | Values are static rather than fetched from the API. |
| 30 | SCAFFOLD_ONLY | Run dashboard renders representative values. | Values are static rather than fetched from the API. |
| 31 | SCAFFOLD_ONLY | Approval API/model tests exist. | Approval state is in-memory. |
| 32 | PARTIAL | Executor abstractions and permission tests exist. | Authority and production deployment path are fake/in-memory. |
| 33 | PARTIAL | Rollback behavior is represented in tests. | Rollback ledger/ownership state is not durable. |
| 34 | SCAFFOLD_ONLY | Monitoring interfaces accept inputs. | No actual post-deployment collection path exists. |
| 35 | PARTIAL | Query-settings action support exists. | It depends on fake/in-memory control state. |
| 36 | PARTIAL | Shift detection is implemented. | Windows and baselines are not persisted. |
| 37 | SCAFFOLD_ONLY | Rewrite recommendations can be produced. | No executable, governed production workflow exists. |
| 38 | SCAFFOLD_ONLY | Cleanup advice can be produced. | No evidence-backed durable implementation exists. |
| 39 | SCAFFOLD_ONLY | Configuration advice can be produced. | No evidence-backed durable implementation exists. |
| 40 | PARTIAL | Redaction/privacy modes have tests. | Strict keyed privacy and persistence constraints are incomplete. |
| 41 | PARTIAL | A real NoSQLBench Docker smoke workload ran. | It is not driven by the real optimizer control plane. |
| 42 | PARTIAL | Deterministic safety scenarios run. | They are not a real adversarial system evaluation. |
| 43 | PARTIAL | Local ablation reporting exists. | It lacks real persisted experimental evidence. |
| 44 | SCAFFOLD_ONLY | API surface and OpenAPI checks exist. | Routes return generic/static `not_configured` data. |
| 45 | SCAFFOLD_ONLY | Expert page renders privacy-safe static evidence states. | It is not backed by a real selected run. |
| 46 | PARTIAL | Provider contracts are tested. | Structured real-provider workflow is incomplete. |
| 47 | PARTIAL | Adapter import boundary is checked. | Production portability is not established. |
| 48 | PARTIAL | Security tests exist. | Durable cross-process security guarantees are not established. |
| 49 | SCAFFOLD_ONLY | Recovery behavior is represented in tests. | Recovery state is in-memory. |
| 50 | PARTIAL | Resource limiter tests exist. | It is not fully integrated with real worker execution. |
| 51 | PARTIAL | Hardware manifest collector reads concrete host/container data. | Manifest is not bound to durable benchmark evidence. |
| 52 | PARTIAL | Export code and tests exist. | Exports do not read the complete durable evidence graph. |
| 53 | PARTIAL | Deterministic demo sequence runs. | It uses safe local/demo state rather than actual control-plane flow. |
| 54 | PARTIAL | Autonomy mode and tests exist. | No real R27-safe autonomous execution path exists. |
| 55 | PARTIAL | Reversion cases are tested. | They do not prove real deployed-index recovery. |
| 56 | PARTIAL | Aggregated acceptance checks passed. | It is not a no-mocks end-to-end system acceptance. |
