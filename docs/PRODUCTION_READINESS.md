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
| R5–R28 | NOT STARTED | Blocked behind the preceding remediation phase. |

## Qualification rule

Production qualification requires completion of the remediation plan’s required
phases and a real, no-mocks system acceptance run. It cannot be inferred from
unit-test counts, a frontend rendering, a Compose health check, or this document.
