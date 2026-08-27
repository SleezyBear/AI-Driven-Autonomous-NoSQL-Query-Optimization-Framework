"""Add durable production authentication state.

Revision ID: 0005_authentication_lifecycle
Revises: 0004_real_control_plane_schema
"""

from alembic import op


revision = "0005_authentication_lifecycle"
down_revision = "0004_real_control_plane_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN role varchar(32) NOT NULL DEFAULT 'VIEWER'")
    op.execute("ALTER TABLE users ADD CONSTRAINT ck_users_role CHECK (role IN ('VIEWER', 'OPERATOR', 'APPROVER', 'ADMIN'))")
    op.execute("CREATE TABLE refresh_tokens (id uuid PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, token_id varchar(64) NOT NULL UNIQUE, token_hash varchar(128) NOT NULL UNIQUE, expires_at timestamptz NOT NULL, revoked_at timestamptz)")
    op.execute("CREATE INDEX ix_refresh_tokens_user ON refresh_tokens (user_id)")
    op.execute("CREATE INDEX ix_refresh_tokens_expiry ON refresh_tokens (expires_at)")


def downgrade() -> None:
    op.execute("DROP TABLE refresh_tokens")
    op.execute("ALTER TABLE users DROP CONSTRAINT ck_users_role")
    op.execute("ALTER TABLE users DROP COLUMN role")
