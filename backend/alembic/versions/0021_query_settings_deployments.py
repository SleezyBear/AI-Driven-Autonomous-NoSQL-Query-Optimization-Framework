"""Durable intent/reconciliation for optimizer-owned query settings."""

from alembic import op


revision = "0021_query_settings"
down_revision = "0020_autonomy_admission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS query_settings_deployments ("
        "id uuid PRIMARY KEY, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, "
        "target_id uuid NOT NULL REFERENCES targets(id) ON DELETE RESTRICT, "
        "optimization_run_id uuid REFERENCES optimization_runs(id) ON DELETE RESTRICT, "
        "query_shape_hash varchar(255) NOT NULL, namespace varchar(320) NOT NULL, "
        "action_fingerprint varchar(128) NOT NULL, idempotency_key varchar(128) NOT NULL UNIQUE, "
        "status varchar(32) NOT NULL, before_state jsonb NOT NULL, intended_state jsonb NOT NULL, "
        "after_state jsonb, inverse_action jsonb NOT NULL, ownership_token varchar(128) NOT NULL, "
        "UNIQUE(target_id, query_shape_hash, ownership_token))"
    )


def downgrade() -> None:
    raise RuntimeError(
        "R24 query-settings deployment evidence is not auto-downgraded; "
        "use an approved maintenance plan."
    )
