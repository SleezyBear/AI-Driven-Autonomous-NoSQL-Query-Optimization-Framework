# R24–R27 Qualification Audit

## Status

- R24: COMPLETE — SYSTEM_PASS
- R25: COMPLETE — INTEGRATION_PASS
- R26: COMPLETE — INTEGRATION_PASS
- R27: COMPLETE — INTEGRATION_PASS
- R28: NOT STARTED

## R24 system evidence

`artifacts/generated/r24-system.json` records `SYSTEM_PASS` across all eight
required real lifecycle paths using real PostgreSQL, MongoDB, Ollama, API,
worker, evaluation/admission, authority, deployment, monitoring, and rollback.

The persisted paths are:

1. `COMPLETED(NO_CANDIDATES)`
2. `COMPLETED(NO_ADMITTED_CANDIDATE)`
3. `COMPLETED(APPROVAL_REJECTED)`
4. approval-controlled `COMPLETED(DEPLOYMENT_SUCCEEDED)`
5. full-autonomous `COMPLETED(DEPLOYMENT_SUCCEEDED)`
6. autonomy-ineligible evidence held at `APPROVAL_PENDING`
7. monitoring regression reaching `ROLLED_BACK`
8. external drift reaching `ROLLBACK_BLOCKED`

Query-settings qualification records exact inverse availability and preservation
of human-created state. Real-stack Playwright passed 3/3.

## R25 evidence

The adversarial/security/statistical suite passed 129 tests.

`artifacts/generated/r25-network-partition.json` records `PASS` for an isolated
three-member replica set:

- one-secondary loss retained majority;
- primary loss recovered through election;
- majority loss failed closed;
- majority restoration recovered;
- exactly one durable marker remained.

## R26 evidence

Concurrency qualification passed 27 tests.

`artifacts/generated/r26-soak.json` records a 60-second qualification soak:

- 4,444 API samples;
- zero failures;
- API p95 90.83 ms;
- maximum 11 PostgreSQL connections;
- maximum 9 MongoDB connections;
- one shared Mongo client;
- asyncio tasks 1 → 1 after cleanup;
- Mongo connections 4 → 4 after cleanup.

## R27 evidence

A direct post-fix qualification recheck passed 46/46 tests across:

- autonomy;
- production;
- monitoring;
- experience;
- rollback;
- reversion.

## Regression-recovery record

The monolithic R24–R27 gate reached its final complete-backend regression after
R24–R27 constituent qualification had passed, but three live MongoDB integration
tests attempted the historical default `127.0.0.1:27017` instead of the gate's
dynamically allocated isolated monitored-Mongo port.

The defect was in acceptance/test configuration, not lifecycle behavior.

Corrections:

- `scripts/run_r24r27_acceptance.sh` exports `MONITORED_MONGODB_URI` using the
  owned dynamic monitored-Mongo port.
- `backend/tests/workloads/test_durable_snapshot.py` uses
  `R19LP_PRODUCTION_TEST_MONGODB_URI` when supplied instead of forcing port
  `27017`.

An isolated recovery run then passed:

- the three previously failing integration tests: 3/3;
- R27 explicit recheck: 46/46;
- complete backend regression: 328 passed, 3 intentional real-provider skips;
- Ruff;
- strict mypy across 109 application source files;
- generated OpenAPI type freshness;
- frontend: 6 files / 9 tests;
- frontend production build;
- system-pass registry validation;
- `git diff --check`.

The recovery ended with:

`R24-R27 TAIL RECOVERY: PASS`

This audit intentionally does **not** claim that a later monolithic
`make r24r27-acceptance` invocation itself exited zero. Closure is based on the
persisted no-mock system evidence plus successful constituent and tail-recovery
evidence.

## Safety

Development PostgreSQL/MongoDB data, snapshots, jobs, namespaces, human-owned
Mongo state, and Docker volumes were not reset or deleted. Qualification used
uniquely owned disposable infrastructure.

## Remaining work

R28 research/reproducibility closure remains.
