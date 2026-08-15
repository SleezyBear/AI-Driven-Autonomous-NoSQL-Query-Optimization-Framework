"""Create the Phase 3 control-plane schema and pgvector extension.

Revision ID: 0001_control_plane_schema
Revises:
Create Date: 2026-08-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_control_plane_schema"
down_revision = None
branch_labels = None
depends_on = None


TABLES = (
    "users",
    "targets",
    "encrypted_secrets",
    "target_evaluation_mappings",
    "target_capability_snapshots",
    "namespaces",
    "query_shapes",
    "telemetry_windows",
    "metric_observations",
    "workload_snapshots",
    "optimization_runs",
    "optimization_candidates",
    "candidate_actions",
    "evaluation_runs",
    "evaluation_trial_pairs",
    "trial_metrics",
    "admission_decisions",
    "safety_check_results",
    "approval_requests",
    "approval_decisions",
    "ledger_entries",
    "rollback_records",
    "experience_records",
    "jobs",
    "audit_events",
    "system_settings",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for table_name in TABLES:
        op.create_table(
            table_name,
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id", name=f"pk_{table_name}"),
        )


def downgrade() -> None:
    for table_name in reversed(TABLES):
        op.drop_table(table_name)
    op.execute("DROP EXTENSION IF EXISTS vector")

