"""Persist production idempotency and crash-recovery state.

Revision ID: 0009_durable_crash_recovery
Revises: 0008_durable_production_ledger
"""

from alembic import op


revision = "0009_durable_crash_recovery"
down_revision = "0008_durable_production_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TABLE production_action_recovery (id uuid PRIMARY KEY, idempotency_key varchar(128) NOT NULL UNIQUE, action_id varchar(128) NOT NULL, target_id uuid NOT NULL, expected_fingerprint varchar(128) NOT NULL, state varchar(32) NOT NULL, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL)")
    op.execute("CREATE INDEX ix_recovery_target_state ON production_action_recovery (target_id, state)")


def downgrade() -> None:
    op.execute("DROP TABLE production_action_recovery")
