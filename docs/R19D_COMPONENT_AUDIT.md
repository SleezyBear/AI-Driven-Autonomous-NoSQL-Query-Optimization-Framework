# R19D component audit

This is a code audit of the post-R19C repository, performed before wiring an
OptimizationRun job to workflow execution. Classifications use the R19D
definitions: **REAL_DURABLE**, **REAL_BUT_NOT_DURABLE**, **SCAFFOLD_ONLY**, or
**MISSING**.

| Required stage/component | Classification | Concrete evidence | R19D consequence |
| --- | --- | --- | --- |
| Persisted run lifecycle and atomic initial job | REAL_DURABLE | `backend/app/runs/service.py:OptimizationRunCreationService`; `backend/app/db/repositories.py:RunRepository`; `backend/app/worker/durable.py:JobRepository` | Authoritative starting boundary. |
| Durable jobs, leases, checkpoints | REAL_DURABLE | `backend/app/worker/durable.py:DurableJobWorker`, `ExecutionContext`, `JobRepository` | Worker ownership is available; orchestration may only use cooperative lease checkpoints. |
| Telemetry/query-shape persistence | REAL_DURABLE | `TelemetryWindow`, `QueryShape`, and `MetricObservation` tables in `backend/app/db/models.py`; repositories in `backend/app/db/repositories.py` | Inputs can be persisted, but are not assembled into a run snapshot by a service. |
| Workload snapshot creation | REAL_BUT_NOT_DURABLE | `backend/app/workloads/snapshots.py:WorkloadSnapshotBuilder` returns a dataclass only. `WorkloadSnapshot` has a PostgreSQL table/repository but no service reads telemetry, builds, persists, attaches, and verifies a snapshot. | **First blocking boundary at `SNAPSHOTTING`.** |
| Diagnosis | SCAFFOLD_ONLY | `backend/app/pipeline/diagnosis.py:DiagnosisPipeline` is callback-driven and holds `DiagnosisPipelineResult` in memory; `AIInvocationRecord` is kept in provider-local `invocations`. | Cannot create a durable diagnosis artifact. |
| Deterministic candidate generation | REAL_BUT_NOT_DURABLE | `backend/app/candidates/index_generator.py:IndexCandidateGenerator` is typed/deterministic, while no service persists it as run-scoped `Candidate`/`CandidateAction` records. | Cannot advance `GENERATING_CANDIDATES`. |
| Experience retrieval | REAL_DURABLE | `backend/app/experience/memory.py:PostgresExperienceRepository` persists pgvector records and performs action-family-gated nearest-neighbor retrieval. | Available only once run-scoped candidate/ranking artifacts exist. |
| AI ranking | REAL_BUT_NOT_DURABLE | `backend/app/ai/provider.py` provides structured, sanitized Ollama output, but invocation records are provider-local and no ranking artifact/order is persisted. | Cannot advance `RANKING`. |
| A/A calibration | REAL_BUT_NOT_DURABLE | Statistical primitives exist in `backend/app/admission/statistics.py`; no durable calibration service/persistence path connects actual benchmark pairs to a run. | Cannot advance `CALIBRATING`. |
| Sandbox evaluation | REAL_BUT_NOT_DURABLE | `backend/app/evaluation/sandbox.py:SandboxIndexEvaluator` and `mongodb_copier.py` use typed actions and real MongoDB copy/verification, but benchmark/admission are callbacks and `EvaluationRun`/trial persistence is not orchestrated. | Cannot advance `EVALUATING`. |
| Statistical admission | REAL_BUT_NOT_DURABLE | `backend/app/admission/statistics.py:evaluate_candidate_admission` is deterministic, but no application service persists decisions and safety results for a run. | Cannot advance `ADMISSION`. |
| Approval authority | REAL_DURABLE | `backend/app/approvals/durable.py:DurableApprovalService` persists expiry/evidence-bound four-eyes approvals. | No run/job `WAITING` resume contract yet. |
| Full-autonomy policy | REAL_BUT_NOT_DURABLE | `backend/app/autonomy/policy.py:approval_required` supplies only a narrow action/mode predicate; required telemetry, ledger, rollback, and permission aggregate policy is absent. | Cannot safely take autonomous deployment path. |
| Production executor | REAL_BUT_NOT_DURABLE | `backend/app/production/executor.py:ProductionExecutor` uses typed actions and verifies target state, but relies on in-memory `ApprovalFlow`/`AppendOnlyLedger`. | Not restart-durable end-to-end. |
| Audit/ledger persistence | REAL_DURABLE | `backend/app/ledger/postgres.py:PostgresProductionLedger`; PostgreSQL audit/ledger repositories. | Available, but not integrated with a durable production execution operation. |
| Post-deployment monitoring | REAL_BUT_NOT_DURABLE | `PostDeploymentMonitor` computes decisions and `PostgresMonitoringEvidenceStore` persists evidence, but callers must supply windows and rollback request; no run-owned monitoring episode exists. | Cannot advance `MONITORING`. |
| Rollback | REAL_BUT_NOT_DURABLE | `backend/app/rollback/owned_index.py:OwnedIndexRollbacker` is ownership/drift safe but uses in-memory ledger. | Not restart-durable end-to-end. |

## Audit conclusion

R19D can safely implement only persisted `CREATED` validation and the
`CREATED → SNAPSHOTTING` transition. It must stop at `SNAPSHOTTING`, because
the required real durable workload-snapshot service is missing. No worker
wiring, lifecycle fabrication, or frontend/API work is permitted at this
boundary.
