# R19L–P implementation audit

This audit records the reusable R4–R18 components and the R19L–P work that is
implemented so far. It is not a production-qualification claim.

| Component | Classification | Reuse/extension decision |
| --- | --- | --- |
| PostgreSQL control-plane models, repositories, and Alembic chain through `0018` | REAL_DURABLE | Additive migrations introduce immutable authority decisions and run-bound deployment artifacts without rewriting historical data. |
| R5 durable approval request/decision service | REAL_DURABLE | Four-eyes requests bind the run, selected candidate fingerprint, and evidence; approval atomically creates/reuses one continuation. |
| R4 RBAC/object authorization | REAL_DURABLE | Reuse existing role and principal checks at approval entry points. |
| R6 PostgreSQL advisory target lock | REAL_DURABLE | Acquire only around production mutation/reconciliation. |
| Typed action schemas | REAL_DURABLE | Accept only the existing typed `CREATE_INDEX` and query-settings families; no arbitrary command path. |
| R7 append-only ledger and R8 recovery checkpoints | REAL_DURABLE | Deployment records intent before external mutation and reconciles exact external effect after restart. |
| Production executor | REAL_DURABLE | `DurableDeploymentService` accepts only authority-bound typed `CREATE_INDEX`, uses a PostgreSQL target lock, and records verified before/after state. |
| Owned-index rollback | REAL_DURABLE | `DurableRollbackService` proves exact ownership/fingerprint/state before dropping an index and returns its persisted terminal outcome on retry. |
| R18 post-deployment monitor/evidence persistence | REAL_DURABLE | `DurableMonitoringService` persists measured evidence, keeps telemetry outages transient, and invokes only durable verified rollback. |
| pgvector experience store | REAL_DURABLE | Factual terminal outcome is idempotently persisted without making correctness depend on embedding generation. |
| Workload, diagnosis, candidates, ranking, evaluation, and admission | REAL_DURABLE | Reuse current R19E–K services and artifacts as pre-deployment authority inputs. |
| `OptimizationRunOrchestrator` through production terminal states | REAL_DURABLE_BY_INJECTION | The orchestrator now advances authority, approval wait, deployment, monitoring, completion, rollback, and rollback-blocked paths only through injected durable services. |
| `OptimizationJobHandler` and durable worker dispatch | REAL_DURABLE | A configured handler calls the real orchestrator; terminal and approval-wait jobs complete idempotently, while transient/integrity outcomes retain their durable retry/failure behavior. |

## Frozen boundaries

- Approval-controlled runs always create human-bound approval requests.
- Full-autonomous runs auto-approve only immutable `AUTO_ELIGIBLE_AFTER_ADMISSION`
  candidates with production-autonomy-eligible evidence; all other cases wait for
  approval with `AUTONOMY_INELIGIBLE_REQUIRES_APPROVAL`.
- Human-gated, recommendation-only, and forbidden actions never become automatic.
- Deployment and rollback use the existing typed executor and ownership checks.
- Integration fixtures use disposable PostgreSQL databases and isolated MongoDB
  namespaces; no long-lived development data or Docker volumes are reset.

## Current implementation evidence

- The focused production lifecycle suite covers real isolated MongoDB
  `CREATE_INDEX`, exact owned rollback, human-index preservation, crash after
  external mutation, retry reconciliation, measured healthy completion, and a
  measured regression that rolls back through the durable monitor.
- All stateful PostgreSQL test families used by the R19L–P chain now create a
  fresh migrated disposable database. Security and auth tests explicitly guard
  against accidental access to the development control-plane database.
- R19L–P remains **in progress** until the complete real-provider acceptance
  target finishes. No readiness or phase-completion status has been changed by
  this audit update.
