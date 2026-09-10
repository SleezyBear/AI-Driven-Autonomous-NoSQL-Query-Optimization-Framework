"""Add immutable grounded diagnosis artifacts and advisory invocation history."""

from alembic import op


revision = "0014_durable_diagnosis"
down_revision = "0013_durable_workload_snapshot"
branch_labels = None
depends_on = None


_IMMUTABLE = ("ai_invocations", "diagnosis_artifacts", "diagnosis_findings")


def upgrade() -> None:
    op.execute("CREATE TABLE ai_invocations (id uuid PRIMARY KEY, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, optimization_run_id uuid NOT NULL REFERENCES optimization_runs(id) ON DELETE RESTRICT, stage varchar(32) NOT NULL, provider varchar(64) NOT NULL, model varchar(256) NOT NULL, prompt_version varchar(64) NOT NULL, schema_version varchar(64) NOT NULL, workload_snapshot_id uuid NOT NULL REFERENCES workload_snapshots(id) ON DELETE RESTRICT, input_hash varchar(128) NOT NULL, sanitized_input json NOT NULL, output_hash varchar(128), validated_output json, latency_ms numeric, status varchar(32) NOT NULL, safe_error_code varchar(128), completed_at timestamptz, attempt_number integer NOT NULL)")
    op.execute("CREATE INDEX ix_ai_invocations_run_stage ON ai_invocations(optimization_run_id, stage, created_at, id)")
    op.execute("CREATE TABLE diagnosis_artifacts (id uuid PRIMARY KEY, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, optimization_run_id uuid NOT NULL UNIQUE REFERENCES optimization_runs(id) ON DELETE RESTRICT, workload_snapshot_id uuid NOT NULL REFERENCES workload_snapshots(id) ON DELETE RESTRICT, target_id uuid NOT NULL REFERENCES targets(id) ON DELETE RESTRICT, ai_invocation_id uuid NOT NULL REFERENCES ai_invocations(id) ON DELETE RESTRICT, schema_version varchar(64) NOT NULL, source_snapshot_fingerprint varchar(128) NOT NULL, deterministic_evidence_hash varchar(128) NOT NULL, artifact_fingerprint varchar(128) NOT NULL UNIQUE)")
    op.execute("CREATE TABLE diagnosis_findings (id uuid PRIMARY KEY, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, diagnosis_artifact_id uuid NOT NULL REFERENCES diagnosis_artifacts(id) ON DELETE RESTRICT, finding_id varchar(128) NOT NULL, finding_type varchar(64) NOT NULL, summary varchar(2048) NOT NULL, rationale varchar(4096) NOT NULL, query_shape_ids json NOT NULL, evidence_refs json NOT NULL, CONSTRAINT uq_diagnosis_finding_identity UNIQUE(diagnosis_artifact_id, finding_id))")
    op.execute("CREATE INDEX ix_diagnosis_findings_artifact ON diagnosis_findings(diagnosis_artifact_id)")
    op.execute("CREATE OR REPLACE FUNCTION reject_diagnosis_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'durable diagnosis evidence is immutable'; END; $$")
    for table in _IMMUTABLE:
        op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_diagnosis_mutation()")


def downgrade() -> None:
    for table in reversed(_IMMUTABLE):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_diagnosis_mutation()")
    op.execute("DROP TABLE diagnosis_findings")
    op.execute("DROP TABLE diagnosis_artifacts")
    op.execute("DROP TABLE ai_invocations")
