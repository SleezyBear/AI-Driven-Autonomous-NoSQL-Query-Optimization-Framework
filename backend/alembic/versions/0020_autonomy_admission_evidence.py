"""Persist whether the frozen admission profile is production eligible."""

from alembic import op


revision = "0020_autonomy_admission"
down_revision = "0019_operational_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE admission_artifacts ADD COLUMN IF NOT EXISTS "
        "production_eligible boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    raise RuntimeError(
        "R27 admission eligibility evidence is not auto-downgraded; "
        "use an approved maintenance plan."
    )
