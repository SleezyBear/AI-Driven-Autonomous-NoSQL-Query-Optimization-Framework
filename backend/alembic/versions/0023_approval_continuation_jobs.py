"""Allow one initial job and one approval continuation per run."""

from alembic import op


revision = "0023_approval_continuation"
down_revision = "0022_candidate_json_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX uq_jobs_initial_optimization_run")
    op.execute(
        "CREATE UNIQUE INDEX uq_jobs_initial_optimization_run ON jobs (optimization_run_id) "
        "WHERE optimization_run_id IS NOT NULL AND kind = 'OPTIMIZATION' "
        "AND COALESCE(payload ->> 'continuation', 'false') <> 'true'"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_jobs_approval_continuation ON jobs (optimization_run_id) "
        "WHERE optimization_run_id IS NOT NULL AND kind = 'OPTIMIZATION' "
        "AND payload ->> 'continuation' = 'true'"
    )


def downgrade() -> None:
    raise RuntimeError(
        "The split initial/continuation job constraints are not auto-downgraded; "
        "use an approved maintenance plan."
    )
