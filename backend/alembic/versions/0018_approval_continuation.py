"""Bind durable approvals to immutable runs and continuation jobs."""

from alembic import op


revision = "0018_approval_continuation"
down_revision = "0017_durable_prod_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS optimization_run_id uuid REFERENCES optimization_runs(id) ON DELETE RESTRICT")
    op.execute("ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS candidate_fingerprint varchar(128)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_approval_request_run ON approval_requests(optimization_run_id) WHERE optimization_run_id IS NOT NULL")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_continuation_optimization_job ON jobs(optimization_run_id, kind, ((payload ->> 'continuation'))) WHERE payload ->> 'continuation' = 'true'")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_continuation_optimization_job")
    op.execute("DROP INDEX IF EXISTS uq_approval_request_run")
    op.execute("ALTER TABLE approval_requests DROP COLUMN IF EXISTS candidate_fingerprint")
    # optimization_run_id predates R19L-P in some accepted development schemas.
