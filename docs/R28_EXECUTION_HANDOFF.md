# R28 Execution Handoff
generated_at: 2026-09-22T14:00:59.382238+00:00

## Audit summary
- authoritative_status: PASSED
- invalidated_legacy_runs: 12
- disk_free: 61.3GiB

## Present scaffolding
- benchmarks/commercebench/dataset.py
- benchmarks/commercebench/validation.py
- benchmarks/ablations.py
- benchmarks/r28_runner.py
- benchmarks/publication.py
- scripts/run_commercebench_profile.py
- artifacts/experiments
- artifacts/raw
- artifacts/generated

## Missing scaffolding

## Authoritative constituents
- commercebench-r28a-standard-b0_native: PASSED (rc=0)
- commercebench-r28a-standard-b1_deterministic_no_gate: PASSED (rc=0)
- commercebench-r28a-standard-b2_llm_rank_no_gate: PASSED (rc=0)
- commercebench-r28a-standard-b3_deterministic_with_gate: PASSED (rc=0)
- commercebench-r28a-standard-b4_llm_with_gate: PASSED (rc=0)
- commercebench-r28a-standard-b5_full_with_experience: PASSED (rc=0)
- safetybench-r28a: PASSED (rc=0)
- nosqlbench-r28a: PASSED (rc=0)
- commercebench-r28b-publication-b0_native: PASSED (rc=0)
- commercebench-r28b-publication-b1_deterministic_no_gate: PASSED (rc=0)
- commercebench-r28b-publication-b2_llm_rank_no_gate: PASSED (rc=0)
- commercebench-r28b-publication-b3_deterministic_with_gate: PASSED (rc=0)
- commercebench-r28b-publication-b4_llm_with_gate: PASSED (rc=0)
- commercebench-r28b-publication-b5_full_with_experience: PASSED (rc=0)

## Resume policy
- Heavy experiments run sequentially; PUBLICATION modes never run concurrently.
- Resume from the first non-PASSED authoritative experiment; never rerun a PASSED one without cause.
- Authoritative IDs use the `commercebench-r28a-` prefix; pre-fix evidence is INVALID and is never counted.
- Use `./nosql/bin/python` for all authoritative Python execution.

## Next commands
- ./nosql/bin/python scripts/experiment_orchestrator.py --mongo-uri <uri> --run-safetybench --run-nosqlbench --run-standard --run-publication
- make publication-repro
- make r28-acceptance
