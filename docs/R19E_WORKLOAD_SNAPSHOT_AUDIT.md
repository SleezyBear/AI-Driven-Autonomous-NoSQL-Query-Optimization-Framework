# R19E workload snapshot audit

## EXISTING_AND_USABLE

- `optimization_runs.workload_snapshot_id` is the authoritative run attachment.
- Completed `telemetry_windows`, `metric_observations`, `query_shapes`, namespaces and target records provide persisted source evidence.
- `PrivacyBoundary` supplies the required HMAC strict-mode pseudonymization; `query_shapes.registry.canonicalize` remains the sole canonicalizer.
- R19B `RunRepository` enforces the run/snapshot target relation; R19D owns the lifecycle transition.

## NEEDS_EXTENSION

- The legacy snapshot parent had no per-run ownership, exact source-window provenance, anchor/range, completeness, or immutable evidence rows.
- Telemetry provider identity exists on windows but must be frozen in the snapshot evidence and completeness record.

## MISSING

- A transactional durable materializer, strict reuse/integrity verification, and database-enforced immutability were missing.
- No snapshot may be treated as a live telemetry query. R19E adds only that capability; diagnosis remains absent.

## Policy

The source is only the monitored run target. R19E selects completed windows ending at the most recent completed anchor, within a 900-second lookback and with a 300-second maximum source age. Base protection is manual-critical OR at least 1% operation share OR at least 1% execution-time share. Candidate-affected protection remains a later-stage union and is not guessed here.
