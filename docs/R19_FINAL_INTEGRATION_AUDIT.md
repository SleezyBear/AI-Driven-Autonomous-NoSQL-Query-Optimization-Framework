# R19 final API and frontend integration audit

## Completion

R19Q–S is complete. The final durable acceptance exited `0`: API tests passed,
the live frontend tests and production build passed, and the R19L–P regression
chain completed with 281 backend tests passed (three deliberate real-provider
skips), Ruff, mypy, pip check, and `git diff --check` all green. No development
PostgreSQL/Mongo data, snapshots, jobs, or Docker volumes were reset or deleted.

This is the starting audit for R19Q–S. It distinguishes durable backend facts
from routes and screens that were previously only generic resource views.

| Seam | Classification | Finding / required integration |
| --- | --- | --- |
| Durable run creation and initial job | REAL_BACKEND_NOT_EXPOSED | `OptimizationRunCreationService` already creates the run and authoritative job atomically; add an authenticated, object-authorized API route. |
| Run list/detail | PARTIAL | Generic paginated `/runs` exposed raw repository rows without ownership filtering or lifecycle relationships; add typed list/detail projections. |
| Approval decision | REAL_BACKEND_NOT_EXPOSED | Durable approval service enforces four-eyes/continuation rules; add authenticated approve/reject actions. |
| Candidate/evaluation/admission/ledger evidence | PARTIAL | Tables were generically readable; detail projection must bind artifacts to one authorized run and represent absence honestly. |
| Auth/RBAC | REAL_CONNECTED | JWT principal and fixed roles exist; object ownership must be applied to run/approval routes. |
| Frontend API client / TanStack Query | PARTIAL | Query infrastructure exists, but routes used generic JSON resource pages. |
| Run list/detail/create frontend | STATIC_FRONTEND | Dashboard cards and `/runs/:id` were placeholders; replace with typed live API screens. |
| Target/workload/expert screens | STATIC_FRONTEND | Existing dashboards contain intentionally static development facts and are not a fallback for run state. |
| Approval UI | MISSING | No API mutation or UI interaction existed. |
| System E2E | MISSING | Existing checks cover durable backend slices; add isolated authenticated API/worker flow before completion. |

## Integration boundary

The browser may talk only to the control-plane API. It must never receive
credentials, raw Mongo commands, secrets, or server-owned lifecycle inputs.
