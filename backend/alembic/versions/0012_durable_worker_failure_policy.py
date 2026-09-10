"""Add durable retry scheduling and sanitized worker failure facts."""

from alembic import op


revision = "0012_worker_failure_policy"
down_revision = "0011_optimization_run_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE jobs ADD COLUMN available_at timestamptz NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE jobs ADD COLUMN last_error_code varchar(128)")
    op.execute("ALTER TABLE jobs ADD COLUMN failed_at timestamptz")
    op.execute("CREATE INDEX ix_jobs_status_available ON jobs (status, available_at, created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_status_available")
    op.execute("ALTER TABLE jobs DROP COLUMN failed_at")
    op.execute("ALTER TABLE jobs DROP COLUMN last_error_code")
    op.execute("ALTER TABLE jobs DROP COLUMN available_at")
