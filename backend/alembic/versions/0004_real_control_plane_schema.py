"""Replace placeholder control-plane tables with the durable relational schema.

Revision ID: 0004_real_control_plane_schema
Revises: 0003_durable_worker_jobs
Create Date: 2026-08-21
"""

from __future__ import annotations

from alembic import op


revision = "0004_real_control_plane_schema"
down_revision = "0003_durable_worker_jobs"
branch_labels = None
depends_on = None


RENAMES = {
    "encrypted_secrets": "target_credentials",
    "target_evaluation_mappings": "evaluation_mappings",
    "target_capability_snapshots": "capability_snapshots",
    "optimization_candidates": "candidates",
    "evaluation_trial_pairs": "trial_pairs",
    "safety_check_results": "safety_results",
    "system_settings": "settings",
}

TABLES = (
    "users", "targets", "target_credentials", "evaluation_mappings", "capability_snapshots",
    "namespaces", "query_shapes", "telemetry_windows", "metric_observations", "workload_snapshots",
    "optimization_runs", "candidates", "candidate_actions", "evaluation_runs", "trial_pairs",
    "trial_metrics", "admission_decisions", "safety_results", "approval_requests", "approval_decisions",
    "ledger_entries", "rollback_records", "experience_records", "jobs", "audit_events", "settings",
)

# Columns added to the original three-column placeholder tables.  PostgreSQL
# types are deliberately explicit: these tables are a durable boundary, not an
# implicit JSON/blob store.
COLUMNS = {
    "users": ("email varchar(320) NOT NULL", "password_hash text NOT NULL", "status varchar(32) NOT NULL DEFAULT 'ACTIVE'", "failed_login_count integer NOT NULL DEFAULT 0", "locked_until timestamptz"),
    "targets": ("owner_user_id uuid NOT NULL", "name varchar(128) NOT NULL", "deployment_mode varchar(32) NOT NULL DEFAULT 'APPROVAL_CONTROLLED'", "state varchar(32) NOT NULL DEFAULT 'ACTIVE'", "connection_label varchar(256) NOT NULL", "is_active boolean NOT NULL DEFAULT true"),
    "target_credentials": ("target_id uuid NOT NULL", "encrypted_payload bytea NOT NULL", "key_version integer NOT NULL", "credential_type varchar(64) NOT NULL"),
    "evaluation_mappings": ("target_id uuid NOT NULL", "evaluation_target_id uuid NOT NULL", "mapping_status varchar(32) NOT NULL DEFAULT 'ACTIVE'"),
    "capability_snapshots": ("target_id uuid NOT NULL", "capabilities jsonb NOT NULL", "fingerprint varchar(128) NOT NULL"),
    "namespaces": ("target_id uuid NOT NULL", "name varchar(256) NOT NULL", "allowlisted boolean NOT NULL DEFAULT false"),
    "query_shapes": ("namespace_id uuid NOT NULL", "shape_hash varchar(128) NOT NULL", "normalized_shape jsonb NOT NULL", "operation varchar(32) NOT NULL"),
    "telemetry_windows": ("target_id uuid NOT NULL", "started_at timestamptz NOT NULL", "ended_at timestamptz NOT NULL", "source varchar(64) NOT NULL", "status varchar(32) NOT NULL"),
    "metric_observations": ("telemetry_window_id uuid NOT NULL", "query_shape_id uuid", "metric_name varchar(64) NOT NULL", "metric_value numeric NOT NULL", "observed_at timestamptz NOT NULL"),
    "workload_snapshots": ("target_id uuid NOT NULL", "telemetry_window_id uuid NOT NULL", "snapshot jsonb NOT NULL", "fingerprint varchar(128) NOT NULL"),
    "optimization_runs": ("target_id uuid NOT NULL", "workload_snapshot_id uuid NOT NULL", "status run_status NOT NULL DEFAULT 'PENDING'", "requested_by_user_id uuid NOT NULL"),
    "candidates": ("optimization_run_id uuid NOT NULL", "query_shape_id uuid NOT NULL", "status candidate_status NOT NULL DEFAULT 'PROPOSED'", "candidate_hash varchar(128) NOT NULL"),
    "candidate_actions": ("candidate_id uuid NOT NULL", "action_type varchar(64) NOT NULL", "action_payload jsonb NOT NULL", "reversible boolean NOT NULL DEFAULT true"),
    "evaluation_runs": ("candidate_id uuid NOT NULL", "status varchar(32) NOT NULL", "environment_fingerprint varchar(128) NOT NULL"),
    "trial_pairs": ("evaluation_run_id uuid NOT NULL", "pair_number integer NOT NULL", "baseline_measurement jsonb NOT NULL", "candidate_measurement jsonb NOT NULL"),
    "trial_metrics": ("trial_pair_id uuid NOT NULL", "metric_name varchar(64) NOT NULL", "baseline_value numeric NOT NULL", "candidate_value numeric NOT NULL"),
    "admission_decisions": ("candidate_id uuid NOT NULL", "verdict varchar(32) NOT NULL", "evidence_hash varchar(128) NOT NULL"),
    "safety_results": ("admission_decision_id uuid NOT NULL", "check_name varchar(64) NOT NULL", "verdict varchar(32) NOT NULL", "details jsonb NOT NULL"),
    "approval_requests": ("admission_decision_id uuid NOT NULL", "requested_by_user_id uuid NOT NULL", "status varchar(32) NOT NULL"),
    "approval_decisions": ("approval_request_id uuid NOT NULL", "decided_by_user_id uuid NOT NULL", "decision varchar(32) NOT NULL", "reason text"),
    "ledger_entries": ("optimization_run_id uuid NOT NULL", "candidate_id uuid", "sequence_number integer NOT NULL", "event_type varchar(64) NOT NULL", "payload_hash varchar(128) NOT NULL"),
    "rollback_records": ("candidate_id uuid NOT NULL", "status varchar(32) NOT NULL", "rollback_payload jsonb NOT NULL"),
    "experience_records": ("evidence jsonb NOT NULL DEFAULT '{}'::jsonb",),
    "jobs": ("optimization_run_id uuid", "kind varchar(64) NOT NULL DEFAULT 'OPTIMIZATION'"),
    "audit_events": ("actor_user_id uuid", "optimization_run_id uuid", "event_type varchar(64) NOT NULL", "event_payload jsonb NOT NULL"),
    "settings": ("scope varchar(64) NOT NULL", "key varchar(128) NOT NULL", "value jsonb NOT NULL"),
}

FOREIGN_KEYS = (
    ("fk_targets_owner", "targets", "owner_user_id", "users", "id", "RESTRICT"),
    ("fk_credentials_target", "target_credentials", "target_id", "targets", "id", "CASCADE"),
    ("fk_mapping_target", "evaluation_mappings", "target_id", "targets", "id", "CASCADE"),
    ("fk_mapping_evaluation_target", "evaluation_mappings", "evaluation_target_id", "targets", "id", "RESTRICT"),
    ("fk_capability_target", "capability_snapshots", "target_id", "targets", "id", "CASCADE"),
    ("fk_namespace_target", "namespaces", "target_id", "targets", "id", "CASCADE"),
    ("fk_shape_namespace", "query_shapes", "namespace_id", "namespaces", "id", "CASCADE"),
    ("fk_window_target", "telemetry_windows", "target_id", "targets", "id", "CASCADE"),
    ("fk_metric_window", "metric_observations", "telemetry_window_id", "telemetry_windows", "id", "CASCADE"),
    ("fk_metric_shape", "metric_observations", "query_shape_id", "query_shapes", "id", "SET NULL"),
    ("fk_snapshot_target", "workload_snapshots", "target_id", "targets", "id", "CASCADE"),
    ("fk_snapshot_window", "workload_snapshots", "telemetry_window_id", "telemetry_windows", "id", "RESTRICT"),
    ("fk_run_target", "optimization_runs", "target_id", "targets", "id", "RESTRICT"),
    ("fk_run_snapshot", "optimization_runs", "workload_snapshot_id", "workload_snapshots", "id", "RESTRICT"),
    ("fk_run_requester", "optimization_runs", "requested_by_user_id", "users", "id", "RESTRICT"),
    ("fk_candidate_run", "candidates", "optimization_run_id", "optimization_runs", "id", "CASCADE"),
    ("fk_candidate_shape", "candidates", "query_shape_id", "query_shapes", "id", "RESTRICT"),
    ("fk_action_candidate", "candidate_actions", "candidate_id", "candidates", "id", "CASCADE"),
    ("fk_evaluation_candidate", "evaluation_runs", "candidate_id", "candidates", "id", "CASCADE"),
    ("fk_pair_evaluation", "trial_pairs", "evaluation_run_id", "evaluation_runs", "id", "CASCADE"),
    ("fk_metric_pair", "trial_metrics", "trial_pair_id", "trial_pairs", "id", "CASCADE"),
    ("fk_admission_candidate", "admission_decisions", "candidate_id", "candidates", "id", "RESTRICT"),
    ("fk_safety_admission", "safety_results", "admission_decision_id", "admission_decisions", "id", "CASCADE"),
    ("fk_request_admission", "approval_requests", "admission_decision_id", "admission_decisions", "id", "RESTRICT"),
    ("fk_request_user", "approval_requests", "requested_by_user_id", "users", "id", "RESTRICT"),
    ("fk_decision_request", "approval_decisions", "approval_request_id", "approval_requests", "id", "CASCADE"),
    ("fk_decision_user", "approval_decisions", "decided_by_user_id", "users", "id", "RESTRICT"),
    ("fk_ledger_run", "ledger_entries", "optimization_run_id", "optimization_runs", "id", "RESTRICT"),
    ("fk_ledger_candidate", "ledger_entries", "candidate_id", "candidates", "id", "SET NULL"),
    ("fk_rollback_candidate", "rollback_records", "candidate_id", "candidates", "id", "RESTRICT"),
    ("fk_experience_candidate", "experience_records", "candidate_id", "candidates", "id", "SET NULL"),
    ("fk_job_run", "jobs", "optimization_run_id", "optimization_runs", "id", "SET NULL"),
    ("fk_audit_actor", "audit_events", "actor_user_id", "users", "id", "SET NULL"),
    ("fk_audit_run", "audit_events", "optimization_run_id", "optimization_runs", "id", "SET NULL"),
)

UNIQUES = (
    ("uq_targets_owner_name", "targets", "owner_user_id, name"),
    ("uq_credentials_target", "target_credentials", "target_id"),
    ("uq_mapping_target", "evaluation_mappings", "target_id"),
    ("uq_namespaces_target_name", "namespaces", "target_id, name"),
    ("uq_query_shapes_namespace_hash", "query_shapes", "namespace_id, shape_hash"),
    ("uq_workload_snapshots_fingerprint", "workload_snapshots", "fingerprint"),
    ("uq_candidates_hash", "candidates", "candidate_hash"),
    ("uq_trial_pairs_run_number", "trial_pairs", "evaluation_run_id, pair_number"),
    ("uq_admission_candidate", "admission_decisions", "candidate_id"),
    ("uq_approval_request_admission", "approval_requests", "admission_decision_id"),
    ("uq_approval_decision_request", "approval_decisions", "approval_request_id"),
    ("uq_ledger_run_sequence", "ledger_entries", "optimization_run_id, sequence_number"),
    ("uq_rollback_candidate", "rollback_records", "candidate_id"),
    ("uq_settings_scope_key", "settings", "scope, key"),
)

INDEXES = (
    ("ix_targets_owner", "targets", "owner_user_id"), ("ix_capabilities_target", "capability_snapshots", "target_id"),
    ("ix_windows_target_started", "telemetry_windows", "target_id, started_at"), ("ix_metrics_window", "metric_observations", "telemetry_window_id"),
    ("ix_runs_target_created", "optimization_runs", "target_id, created_at"), ("ix_candidates_run", "candidates", "optimization_run_id"),
    ("ix_evaluations_candidate", "evaluation_runs", "candidate_id"), ("ix_ledger_run", "ledger_entries", "optimization_run_id"),
    ("ix_audit_actor_created", "audit_events", "actor_user_id, created_at"),
)

CHECKS = (
    ("ck_telemetry_window_order", "telemetry_windows", "ended_at >= started_at"),
    ("ck_metric_observation_nonnegative", "metric_observations", "metric_value >= 0"),
    ("ck_trial_pair_number_positive", "trial_pairs", "pair_number > 0"),
    ("ck_ledger_sequence_positive", "ledger_entries", "sequence_number > 0"),
    ("ck_job_attempts_nonnegative", "jobs", "attempts >= 0"),
)


def _create_enum(name: str, values: str) -> None:
    op.execute(f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({values}); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")


def upgrade() -> None:
    _create_enum("run_status", "'PENDING', 'RUNNING', 'COMPLETED', 'FAILED'")
    _create_enum("candidate_status", "'PROPOSED', 'EVALUATING', 'ADMITTED', 'REJECTED'")
    for old, new in RENAMES.items():
        op.rename_table(old, new)
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN id TYPE uuid USING id::uuid")
    op.execute("ALTER TABLE experience_records ALTER COLUMN candidate_id TYPE uuid USING candidate_id::uuid")
    op.execute("ALTER TABLE jobs ALTER COLUMN status TYPE varchar(16) USING status::varchar")
    for table, definitions in COLUMNS.items():
        for definition in definitions:
            op.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
    for name, table, column, target, target_column, ondelete in FOREIGN_KEYS:
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({column}) REFERENCES {target} ({target_column}) ON DELETE {ondelete}")
    for name, table, columns in UNIQUES:
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE ({columns})")
    for name, table, columns in INDEXES:
        op.execute(f"CREATE INDEX {name} ON {table} ({columns})")
    for name, table, condition in CHECKS:
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({condition})")


def downgrade() -> None:
    for name, table, _ in reversed(CHECKS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    for name, table, _ in reversed(INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
    for name, table, _ in reversed(UNIQUES):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    for name, table, _, _, _, _ in reversed(FOREIGN_KEYS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    for table, definitions in reversed(tuple(COLUMNS.items())):
        for definition in reversed(definitions):
            column = definition.split()[0]
            if table == "jobs" and column in {"payload", "status", "lease_owner", "lease_expires_at", "heartbeat_at", "attempts", "completed_at"}:
                continue
            if table == "experience_records" and column in {"candidate_id", "outcome", "embedding"}:
                continue
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN id TYPE varchar(36) USING id::text")
    op.execute("ALTER TABLE experience_records ALTER COLUMN candidate_id TYPE varchar(36) USING candidate_id::text")
    for new, old in reversed(tuple((new, old) for old, new in RENAMES.items())):
        op.rename_table(new, old)
    op.execute("DROP TYPE IF EXISTS candidate_status")
    op.execute("DROP TYPE IF EXISTS run_status")
