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
| R1–R28 | NOT STARTED | Blocked behind the preceding remediation phase. |

## Qualification rule

Production qualification requires completion of the remediation plan’s required
phases and a real, no-mocks system acceptance run. It cannot be inferred from
unit-test counts, a frontend rendering, a Compose health check, or this document.
