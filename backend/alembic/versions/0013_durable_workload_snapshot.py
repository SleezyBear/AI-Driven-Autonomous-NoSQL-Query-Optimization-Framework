"""Add immutable, provenance-backed workload snapshots."""

from alembic import op


revision = "0013_durable_workload_snapshot"
down_revision = "0012_worker_failure_policy"
branch_labels = None
depends_on = None


def _immutable(table: str) -> None:
    op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_workload_snapshot_mutation()")


def upgrade() -> None:
    op.execute("ALTER TABLE workload_snapshots ADD COLUMN source_run_id uuid UNIQUE REFERENCES optimization_runs(id) ON DELETE RESTRICT")
    op.execute("ALTER TABLE workload_snapshots ADD COLUMN observed_from timestamptz")
    op.execute("ALTER TABLE workload_snapshots ADD COLUMN observed_until timestamptz")
    op.execute("ALTER TABLE workload_snapshots ADD COLUMN anchor_at timestamptz")
    op.execute("ALTER TABLE workload_snapshots ADD COLUMN completeness json")
    op.execute("CREATE TABLE workload_snapshot_source_windows (id uuid PRIMARY KEY, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, workload_snapshot_id uuid NOT NULL REFERENCES workload_snapshots(id) ON DELETE RESTRICT, telemetry_window_id uuid NOT NULL REFERENCES telemetry_windows(id) ON DELETE RESTRICT, CONSTRAINT uq_snapshot_source_window UNIQUE (workload_snapshot_id, telemetry_window_id))")
    op.execute("CREATE TABLE workload_snapshot_query_shapes (id uuid PRIMARY KEY, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, workload_snapshot_id uuid NOT NULL REFERENCES workload_snapshots(id) ON DELETE RESTRICT, query_shape_id uuid NOT NULL REFERENCES query_shapes(id) ON DELETE RESTRICT, query_shape_hash varchar(128) NOT NULL, operation varchar(32) NOT NULL, namespace varchar(256) NOT NULL, observed_operation_count integer NOT NULL, successful_operation_count integer, failure_count integer, timeout_count integer, aggregate_execution_time_ms numeric, workload_operation_share numeric NOT NULL, execution_time_share numeric, manually_critical boolean NOT NULL DEFAULT false, protected_manual_critical boolean NOT NULL DEFAULT false, protected_operation_share boolean NOT NULL DEFAULT false, protected_execution_time_share boolean NOT NULL DEFAULT false, base_protected boolean NOT NULL DEFAULT false, provider varchar(64) NOT NULL, CONSTRAINT uq_snapshot_query_shape UNIQUE (workload_snapshot_id, query_shape_id))")
    op.execute("CREATE INDEX ix_workload_snapshot_query_shapes_snapshot ON workload_snapshot_query_shapes(workload_snapshot_id)")
    op.execute("CREATE TABLE workload_snapshot_metrics (id uuid PRIMARY KEY, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, workload_snapshot_id uuid NOT NULL REFERENCES workload_snapshots(id) ON DELETE RESTRICT, source_metric_observation_id uuid NOT NULL UNIQUE REFERENCES metric_observations(id) ON DELETE RESTRICT, scope varchar(32) NOT NULL, metric_name varchar(64) NOT NULL, metric_value numeric NOT NULL)")
    op.execute("CREATE INDEX ix_workload_snapshot_metrics_snapshot ON workload_snapshot_metrics(workload_snapshot_id)")
    op.execute("CREATE OR REPLACE FUNCTION reject_workload_snapshot_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'workload snapshots are immutable'; END; $$")
    for table in ("workload_snapshots", "workload_snapshot_source_windows", "workload_snapshot_query_shapes", "workload_snapshot_metrics"):
        _immutable(table)


def downgrade() -> None:
    for table in ("workload_snapshot_metrics", "workload_snapshot_query_shapes", "workload_snapshot_source_windows", "workload_snapshots"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_workload_snapshot_mutation()")
    op.execute("DROP TABLE workload_snapshot_metrics")
    op.execute("DROP TABLE workload_snapshot_query_shapes")
    op.execute("DROP TABLE workload_snapshot_source_windows")
    op.execute("ALTER TABLE workload_snapshots DROP COLUMN completeness")
    op.execute("ALTER TABLE workload_snapshots DROP COLUMN anchor_at")
    op.execute("ALTER TABLE workload_snapshots DROP COLUMN observed_until")
    op.execute("ALTER TABLE workload_snapshots DROP COLUMN observed_from")
    op.execute("ALTER TABLE workload_snapshots DROP COLUMN source_run_id")
