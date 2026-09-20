"""Add R22 indexes for bounded control-plane operational reads."""

from alembic import op


revision = "0019_operational_indexes"
down_revision = "0018_approval_continuation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_claim_pending "
        "ON jobs (available_at, created_at, id) WHERE status = 'PENDING'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_claim_expired "
        "ON jobs (lease_expires_at, created_at, id) WHERE status = 'RUNNING'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_runs_requester_created "
        "ON optimization_runs (requested_by_user_id, created_at DESC, id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_runs_target_created "
        "ON optimization_runs (target_id, created_at DESC, id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_approvals_status_expiry "
        "ON approval_requests (status, expires_at, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_production_ledger_created "
        "ON production_ledger_entries (created_at, entry_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_run_created "
        "ON audit_events (optimization_run_id, created_at, id)"
    )


def downgrade() -> None:
    raise RuntimeError(
        "R22 operational indexes are not auto-downgraded; use an approved maintenance plan."
    )
