"""Add pgvector-backed experience-memory fields.

Revision ID: 0002_experience_memory_pgvector
Revises: 0001_control_plane_schema
Create Date: 2026-08-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "0002_experience_memory_pgvector"
down_revision = "0001_control_plane_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("experience_records", sa.Column("candidate_id", sa.String(length=36), nullable=True))
    op.add_column("experience_records", sa.Column("outcome", sa.String(length=64), nullable=True))
    op.add_column("experience_records", sa.Column("embedding", Vector(768), nullable=True))


def downgrade() -> None:
    op.drop_column("experience_records", "embedding")
    op.drop_column("experience_records", "outcome")
    op.drop_column("experience_records", "candidate_id")
