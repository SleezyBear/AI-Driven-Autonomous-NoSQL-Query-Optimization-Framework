# Production Readiness

## Remediation baseline

This document is the authoritative readiness record for the Production-Readiness
Remediation Plan. It supersedes claims of production completion in the original
phase plan. Historical tests remain useful evidence, but passing them does not
prove that the promised system operated end-to-end against real infrastructure.

| Evidence label | Meaning |
| --- | --- |
| `UNIT_PASS` | An isolated deterministic test passed. It may use fakes, callbacks, or in-memory state. |
| `INTEGRATION_PASS` | A concrete component boundary was exercised, such as a Docker service, migration, or frontend build. |
| `SYSTEM_PASS` | A registered no-mocks acceptance test completed an actual end-to-end workflow against applicable infrastructure. |

No original phase currently has a `SYSTEM_PASS`; therefore none is production
qualified. `scripts/check_system_pass_registry.py` enforces that every future
`SYSTEM_PASS` has a registered system acceptance test.

## Remediation status

| Remediation phase | Status | Evidence |
| --- | --- | --- |
| R0 — truthful state | COMPLETE — UNIT_PASS | Historical claims are reclassified independently of `PHASE_STATUS.md`; the system-pass registry guard is tested. |
| R1 — Python/runtime lifecycle migration | COMPLETE — INTEGRATION_PASS | uv-managed CPython 3.12.14 x86_64, unchanged pinned requirements, 196 backend tests, static checks, and rebuilt API/worker images passed; system `python3` remains 3.14.6. |
| R2 — relational control-plane schema | COMPLETE — INTEGRATION_PASS | Corrective migration 0004 defines UUID-backed models, ownership FKs, unique/check constraints, and indexes; disposable PostgreSQL upgrade/downgrade/upgrade inspection passed. |
| R3 — real persistence repositories | COMPLETE — INTEGRATION_PASS | PostgreSQL repositories now cover every durable domain; state and a pending job survived rebuilt/restarted API and worker containers and were recovered through fresh repository engines. |
| R4 — production-grade authentication | COMPLETE — INTEGRATION_PASS | PostgreSQL-backed users and refresh-token sessions enforce explicit JWT configuration, rotation/revocation, user disablement, expiry/type rejection, five-attempt lockout, and persisted authentication audit events. |
| R5 — durable distributed authorization and approvals | COMPLETE — INTEGRATION_PASS | PostgreSQL transactions persist evidence-bound approvals and decisions with four-eyes enforcement; separate repository engines and restarted API/worker containers proved visibility and continued validity before expiry. |
| R6 — distributed target locking | COMPLETE — INTEGRATION_PASS | PostgreSQL session advisory locks derived solely from target IDs excluded a competing independent worker; authority was safely recoverable after release. |
| R7 — durable production ledger | COMPLETE — INTEGRATION_PASS | PostgreSQL ledger rows contain the required state/action and hash-chain evidence; restart verification passed and privileged disposable-row tampering was detected. |
| R8 — durable crash recovery and idempotency | COMPLETE — INTEGRATION_PASS | Persisted intent and `INTENT_RECORDED`/`EXECUTION_STARTED`/`EFFECT_OBSERVED`/`EXECUTION_CONFIRMED` state support restart recovery; an observed exact effect was confirmed without duplicate mutation. |
| R9 — complete API implementation | COMPLETE — INTEGRATION_PASS | Every required `/api/v1` group now exposes a paginated persisted resource route rather than a fabricated `not_configured` response; target reads are ownership-filtered and target creation is explicit. |
| R10 — correct metric semantics | COMPLETE — UNIT_PASS | Latency percentiles and throughput use successful operations only, failures remain independently counted, and cumulative server counters are differenced into canonical utilization and per-operation values. |
| R11 — telemetry correctness and privacy | COMPLETE — UNIT_PASS | MongoDB 8-shaped query-stats, profiler, current-op, and structured diagnostic-log records are normalized without literals; strict privacy uses keyed HMAC pseudonyms for identifiers and values. |
| R12 — real CommerceBench | COMPLETE — UNIT_PASS | Exact SMOKE, STANDARD, and PUBLICATION record-count contracts, mixed read/write workload shapes, generator version, and content-derived dataset fingerprints are defined; the SMOKE dataset materializes the required 34,500 records deterministically. |
| R13 — real MongoDB benchmark executor | COMPLETE — INTEGRATION_PASS | Real MongoDB 8 CommerceBench execution restores both AB/BA arms, verifies the environment, warms up and schedules mixed operations, records monotonic successful/error/timeout timing and counter deltas, and writes typed trial evidence. |
| R14 — statistical correctness | COMPLETE — UNIT_PASS | Pair sufficiency is enforced per protected metric; higher-is-better zero behavior is explicit; a three-observation minimum applies; and a shared-resample paired max-statistic bootstrap supplies simultaneous protected-family safety evidence. |
| R15–R28 | NOT STARTED | Blocked behind the preceding remediation phase. |

## Qualification rule

Production qualification requires completion of the remediation plan’s required
phases and a real, no-mocks system acceptance run. It cannot be inferred from
unit-test counts, a frontend rendering, a Compose health check, or this document.
