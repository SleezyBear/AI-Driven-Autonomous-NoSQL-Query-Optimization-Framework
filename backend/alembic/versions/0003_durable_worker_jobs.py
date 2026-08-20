"""Add durable lease-based worker fields to the jobs table.

Revision ID: 0003_durable_worker_jobs
Revises: 0002_experience_memory_pgvector
Create Date: 2026-08-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_durable_worker_jobs"
down_revision = "0002_experience_memory_pgvector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
    op.add_column("jobs", sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"))
    op.add_column("jobs", sa.Column("lease_owner", sa.String(length=128), nullable=True))
    op.add_column("jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_jobs_claimable", "jobs", ["status", "lease_expires_at", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_claimable", table_name="jobs")
    op.drop_column("jobs", "completed_at")
    op.drop_column("jobs", "attempts")
    op.drop_column("jobs", "heartbeat_at")
    op.drop_column("jobs", "lease_expires_at")
    op.drop_column("jobs", "lease_owner")
    op.drop_column("jobs", "status")
    op.drop_column("jobs", "payload")
