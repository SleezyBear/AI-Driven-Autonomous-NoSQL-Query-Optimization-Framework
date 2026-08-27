"""Bind persisted approval requests to an immutable deployable action.

Revision ID: 0007_durable_approvals
Revises: 0006_user_auth_constraints
"""

from alembic import op


revision = "0007_durable_approvals"
down_revision = "0006_user_auth_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE approval_requests ALTER COLUMN admission_decision_id DROP NOT NULL")
    op.execute("ALTER TABLE approval_requests ADD COLUMN action_id varchar(128)")
    op.execute("ALTER TABLE approval_requests ADD COLUMN target_id uuid")
    op.execute("ALTER TABLE approval_requests ADD COLUMN candidate_id uuid")
    op.execute("ALTER TABLE approval_requests ADD COLUMN evidence_hash varchar(128)")
    op.execute("ALTER TABLE approval_requests ADD COLUMN expires_at timestamptz")
    op.execute("ALTER TABLE approval_requests ADD CONSTRAINT fk_approval_target FOREIGN KEY (target_id) REFERENCES targets(id) ON DELETE RESTRICT")
    op.execute("CREATE INDEX ix_approval_action_target ON approval_requests (action_id, target_id)")
    op.execute("CREATE INDEX ix_approval_expiry ON approval_requests (expires_at)")


def downgrade() -> None:
    op.execute("DROP INDEX ix_approval_expiry")
    op.execute("DROP INDEX ix_approval_action_target")
    op.execute("ALTER TABLE approval_requests DROP CONSTRAINT fk_approval_target")
    op.execute("ALTER TABLE approval_requests DROP COLUMN expires_at")
    op.execute("ALTER TABLE approval_requests DROP COLUMN evidence_hash")
    op.execute("ALTER TABLE approval_requests DROP COLUMN candidate_id")
    op.execute("ALTER TABLE approval_requests DROP COLUMN target_id")
    op.execute("ALTER TABLE approval_requests DROP COLUMN action_id")
    op.execute("ALTER TABLE approval_requests ALTER COLUMN admission_decision_id SET NOT NULL")
