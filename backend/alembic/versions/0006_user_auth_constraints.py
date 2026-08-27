"""Restore the user e-mail uniqueness contract omitted by the placeholder schema.

Revision ID: 0006_user_auth_constraints
Revises: 0005_authentication_lifecycle
"""

from alembic import op


revision = "0006_user_auth_constraints"
down_revision = "0005_authentication_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD CONSTRAINT uq_users_email UNIQUE (email)")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT uq_users_email")
