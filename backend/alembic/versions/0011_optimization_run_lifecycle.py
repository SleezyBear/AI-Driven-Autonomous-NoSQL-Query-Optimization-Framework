"""Persist the complete optimization lifecycle and atomic initial-job identity.

Revision ID: 0011_optimization_run_lifecycle
Revises: 0010_durable_pgvector_experience
"""

from alembic import op

revision = "0011_optimization_run_lifecycle"
down_revision = "0010_durable_pgvector_experience"
branch_labels = None
depends_on = None

_STATES = "'CREATED','SNAPSHOTTING','DIAGNOSING','GENERATING_CANDIDATES','RANKING','CALIBRATING','EVALUATING','ADMISSION','ADMITTED','APPROVAL_PENDING','APPROVED','DEPLOYING','DEPLOYED','MONITORING','COMPLETED','ROLLED_BACK','ROLLBACK_BLOCKED','FAILED'"


def upgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM optimization_runs WHERE status::text = 'RUNNING') THEN RAISE EXCEPTION 'cannot migrate RUNNING optimization_runs: lifecycle stage is ambiguous'; END IF; END $$")
    op.execute("ALTER TABLE optimization_runs ALTER COLUMN status DROP DEFAULT")
    op.execute(f"CREATE TYPE run_status_replacement AS ENUM ({_STATES})")
    op.execute("ALTER TABLE optimization_runs ALTER COLUMN status TYPE run_status_replacement USING (CASE status::text WHEN 'PENDING' THEN 'CREATED' WHEN 'COMPLETED' THEN 'COMPLETED' WHEN 'FAILED' THEN 'FAILED' END)::run_status_replacement")
    op.execute("DROP TYPE run_status")
    op.execute("ALTER TYPE run_status_replacement RENAME TO run_status")
    op.execute("ALTER TABLE optimization_runs ALTER COLUMN status SET DEFAULT 'CREATED'::run_status")
    op.execute("ALTER TABLE optimization_runs ALTER COLUMN workload_snapshot_id DROP NOT NULL")
    op.execute("ALTER TABLE optimization_runs ADD COLUMN deployment_mode varchar(32)")
    op.execute("UPDATE optimization_runs AS run SET deployment_mode = target.deployment_mode FROM targets AS target WHERE target.id = run.target_id")
    op.execute("ALTER TABLE optimization_runs ALTER COLUMN deployment_mode SET NOT NULL")
    op.execute("ALTER TABLE optimization_runs ADD COLUMN primary_metric_key varchar(256)")
    op.execute("ALTER TABLE optimization_runs ADD CONSTRAINT ck_run_deployment_mode CHECK (deployment_mode IN ('APPROVAL_CONTROLLED', 'FULL_AUTONOMOUS'))")
    op.execute("ALTER TABLE optimization_runs ADD CONSTRAINT ck_run_primary_metric_key CHECK (primary_metric_key IS NULL OR length(primary_metric_key) > 0)")
    op.execute("CREATE UNIQUE INDEX uq_jobs_initial_optimization_run ON jobs (optimization_run_id) WHERE optimization_run_id IS NOT NULL AND kind = 'OPTIMIZATION'")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM optimization_runs WHERE status::text NOT IN ('CREATED','COMPLETED','FAILED')) THEN RAISE EXCEPTION 'cannot downgrade active optimization lifecycle states safely'; END IF; IF EXISTS (SELECT 1 FROM optimization_runs WHERE workload_snapshot_id IS NULL) THEN RAISE EXCEPTION 'cannot downgrade optimization runs without workload snapshots safely'; END IF; END $$")
    op.execute("DROP INDEX IF EXISTS uq_jobs_initial_optimization_run")
    op.execute("ALTER TABLE optimization_runs DROP CONSTRAINT ck_run_primary_metric_key")
    op.execute("ALTER TABLE optimization_runs DROP CONSTRAINT ck_run_deployment_mode")
    op.execute("ALTER TABLE optimization_runs DROP COLUMN primary_metric_key")
    op.execute("ALTER TABLE optimization_runs DROP COLUMN deployment_mode")
    op.execute("ALTER TABLE optimization_runs ALTER COLUMN status DROP DEFAULT")
    op.execute("CREATE TYPE run_status_old AS ENUM ('PENDING','RUNNING','COMPLETED','FAILED')")
    op.execute("ALTER TABLE optimization_runs ALTER COLUMN status TYPE run_status_old USING (CASE status::text WHEN 'CREATED' THEN 'PENDING' WHEN 'COMPLETED' THEN 'COMPLETED' WHEN 'FAILED' THEN 'FAILED' END)::run_status_old")
    op.execute("DROP TYPE run_status")
    op.execute("ALTER TYPE run_status_old RENAME TO run_status")
    op.execute("ALTER TABLE optimization_runs ALTER COLUMN status SET DEFAULT 'PENDING'::run_status")
    op.execute("ALTER TABLE optimization_runs ALTER COLUMN workload_snapshot_id SET NOT NULL")
