# Pre-Phase-15 audit

overall_status: PASS

This one-time audit covers implemented Phases 0–14. `DEFERRED` items name the phase that introduces the affected production capability; they do not permit an unsafe current operation.

| Item | Status | Evidence / disposition |
| --- | --- | --- |
| A Environment and dependencies | PASS | `make preflight`; `scripts/verify_environment.py`; `scripts/verify_requirements.py`; all require CPython 3.10/x86_64 and `nosql/`. |
| B Secrets and source control | FAIL → FIXED | `scripts/audit_tracked_secrets.py` checks `git ls-files` without printing values; `.env.example` has placeholders only. |
| C FastAPI error handling | FAIL → FIXED | `app.main.request_context` returns a generic 500 and request ID; no exception detail enters the response. |
| D Request ID / structured logging | FAIL → FIXED | `app.main.request_context` emits structured `structlog` request events; `app.security.redaction.redact_value` is the canonical redactor. |
| E CORS | FAIL → FIXED | `CORSMiddleware` allows configured origins only; production rejects wildcard origins. |
| F Trusted host | FAIL → FIXED | `TrustedHostMiddleware` uses explicit configured hosts and production rejects wildcards. |
| G API input boundary | PASS | Existing Phase 1–5 public routes accept only typed Pydantic input; no command/query/action dictionaries or unbounded table endpoint exists. Future identifier-bearing APIs are deferred to Phase 44. |
| H Object authorization | DEFERRED_TO_PHASE_31 | Approval/candidate/evaluation persistence and target-scoped endpoints do not exist yet; no current endpoint resolves a stored cross-target object. |
| I Authentication | FAIL → FIXED | `PasswordService` uses Argon2id and enforces 12–128 characters; `backend/tests/auth/test_rbac.py`. |
| J Brute-force login protection | NOT_APPLICABLE | No login endpoint/account persistence exists in Phases 0–14; authoritative PostgreSQL-backed login limiting is deferred to Phase 44. |
| K JWT | FAIL → FIXED | `JwtService` fixes HS256, requires exp/iat/sub/token_type, and separates 15-minute access from 7-day refresh tokens. Runtime signing material is never committed. |
| L RBAC | PASS | `backend/tests/auth/test_rbac.py` covers VIEWER denial, operator authority, and self-approval denial. |
| M Control database relationships | DEFERRED_TO_PHASE_44 | Phase 3 provides Alembic/asyncpg/SQLAlchemy schema foundations; relationship-bearing API persistence has not yet been introduced. |
| N Transactions | DEFERRED_TO_PHASE_44 | No multi-row control-plane workflow exists before durable API persistence. |
| O Timestamps | PASS | `MetricCollector` uses `perf_counter`; no Phase 0–14 application persistence writes a wall-clock record. Future persisted timestamps are deferred to Phase 44. |
| P Secret store | PASS | `backend/tests/security/test_secret_encryption.py` validates AES-256-GCM, random 12-byte nonces, AAD/key-version rejection, and no plaintext fallback. |
| Q URI redaction | FAIL → FIXED | `app.security.redaction.redact_connection_uri` is used as the canonical redaction layer. |
| R Mongo connection safety | DEFERRED_TO_PHASE_20 | Target connection configuration/lifecycle is introduced with sandbox evaluation; Phase 7 capability test has explicit finite command timeout. |
| S Mongo TLS | DEFERRED_TO_PHASE_20 | Remote target creation does not exist; local Docker is intentionally non-TLS. |
| T Mongo pools/lifecycle | DEFERRED_TO_PHASE_20 | Lifecycle-managed production target clients do not exist before sandbox evaluation. |
| U Namespace safety | DEFERRED_TO_PHASE_19 | Candidate generation and target namespace configuration begin in deterministic index generation. |
| V Observer/executor credentials | PASS | `backend/tests/mongodb/test_executor_permissions.py` repeats destructive-operation denials; Compose mounts executor secret only to worker in the implemented topology. |
| W Adapter boundary | PASS | `backend/tests/adapters/test_database_adapter_contract.py`; `DatabaseAdapter` exposes no raw command method. |
| X Retries | NOT_APPLICABLE | No retrying production mutation path exists before typed actions in Phase 18. |
| Y Telemetry privacy | PASS | `backend/app/query_shapes/registry.py` canonicalizes literals to type tokens; `backend/tests/query_shapes/test_registry.py`. |
| Z Telemetry load | PASS | `backend/tests/telemetry/test_provider_selection.py` proves profiler is not enabled; capability commands use a finite timeout. |
| AA Query shapes | PASS | `backend/tests/query_shapes/test_registry.py` covers server hash preference and literal-free deterministic fallback. |
| AB Metric units | DEFERRED_TO_PHASE_15 | The Phase 15 typed metric-policy layer validates finite canonical comparison values; Phase 11 has only collection normalization. |
| AC Latency/throughput | PASS | `MetricCollector` uses `perf_counter` and separately retains error/timeout counts; controlled arm aggregation is implemented in Phase 15. |
| AD Snapshot immutability | PASS | `backend/tests/workloads/test_snapshots.py` verifies frozen snapshot fields and copied fingerprint facts. |
| AE Query-shape protection | PASS | `test_90_9_1_distribution_protects_all_query_shapes` protects the exact 1% share. |
| AF CommerceBench | FAIL → FIXED | `CommerceBench` owns a private RNG with seed 42; fingerprint now includes generator version, profile, counts, index/query-settings state; deterministic reset test passes. |
| AG Evaluation separation | DEFERRED_TO_PHASE_20 | Evaluation-target wiring and candidate action first exist in sandbox evaluation. |
| AH Starting state | PASS | `backend/tests/benchmarks/test_runner.py` verifies matching baseline/candidate starting fingerprints. |
| AI Order bias | FAIL → FIXED | Phase 15 adds deterministic AB/BA selection and persisted order to the Phase 14 record. |
| AJ Arm failure | DEFERRED_TO_PHASE_20 | Real arm cleanup/failure state is introduced with sandbox action execution; current runner has no database mutation. |
| AK Benchmark concurrency | DEFERRED_TO_PHASE_22 | No background benchmark API exists; the explicit general isolation lock belongs to Phase 22. |
| AL Fingerprints | FAIL → FIXED | `benchmarks/commercebench/dataset.py` hashes canonical contents plus profile/version/counts/index/query-settings facts without secrets. |
| AM Health endpoints | PASS | `backend/tests/test_health.py` confirms liveness/readiness are process-local. |
| AN Test isolation | PASS | Existing tests use local Docker Mongo, fake adapter, or pure in-memory data; no Ollama test runs. |
| AO Fail closed | PASS | Secret authentication failures raise; capability/permission tests reject missing authority; Phase 15 adds fail-closed statistical verdicts. |

Audit regression command: `make phase0-acceptance && ./nosql/bin/python -m pytest backend/tests && ./nosql/bin/ruff check backend && ./nosql/bin/mypy backend/app`.
