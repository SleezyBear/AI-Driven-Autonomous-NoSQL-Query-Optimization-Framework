# R19F diagnosis audit

This audit covers the post-R19E codebase before adding the durable diagnosis
boundary. Classifications use the corrective-plan vocabulary.

## EXISTING_AND_USABLE

- `backend/app/workloads/durable.py:WorkloadSnapshotService` provides a
  run-bound immutable snapshot, typed `SnapshotRead`, target/run validation,
  and deterministic integrity verification.
- `backend/app/runs/orchestrator.py:OptimizationRunOrchestrator` owns the
  persisted lifecycle prefix and performs cooperative worker-lease checks.
- `backend/app/telemetry/providers.py` and the R19E snapshot materializer
  preserve privacy-safe query-shape evidence and the currentOp autonomy
  limitation.
- `backend/app/ai/prompts/v1/diagnosis.txt` is an existing versioned prompt
  location, and `OllamaAIProvider` already requests JSON-schema-constrained
  output under the shared Ollama/benchmark isolation lock.

## NEEDS_EXTENSION

- `backend/app/ai/provider.py:AIProvider` needs a diagnosis-specific typed
  artifact contract and provider/model metadata suitable for durable audit
  persistence. Its current `diagnose` method returns the legacy scaffold
  schema.
- `backend/app/db/models.py` and persistence repositories need immutable,
  run-scoped diagnosis, finding, finding-reference, and append-only AI
  invocation records.
- `OptimizationRunOrchestrator` must invoke a durable diagnosis service only
  at `DIAGNOSING`, verify the artifact, re-check its lease, and transition no
  farther than `GENERATING_CANDIDATES`.

## SCAFFOLD_ONLY

- `backend/app/pipeline/diagnosis.py:DiagnosisPipeline.run` is callback-driven,
  carries `DiagnosisPipelineResult` only in memory, and is not a durable,
  restart-safe run-scoped diagnosis boundary. It is retained only for legacy
  compatibility and must not be the production R19D path.
- The existing provider-local `AIInvocationRecord` list is process memory,
  not an audit record.

## MISSING

- An additive schema migration after `0013_durable_workload_snapshot` for
  immutable authoritative diagnosis artifacts, typed findings/references, and
  append-only invocation attempts.
- A production `DiagnosisService.create_for_run` that builds a deterministic,
  literal-free evidence view exclusively from the immutable snapshot, validates
  structured grounded output, persists/reuses one artifact per run, and
  verifies its fingerprint.
