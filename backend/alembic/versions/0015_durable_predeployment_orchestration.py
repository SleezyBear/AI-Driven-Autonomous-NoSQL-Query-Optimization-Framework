"""Add immutable durable artifacts for the R19G-K pre-deployment workflow."""

from alembic import op


revision = "0015_predeployment_orchestration"
down_revision = "0014_durable_diagnosis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE run_completion_reason AS ENUM ('NO_CANDIDATES', 'NO_ADMITTED_CANDIDATE', 'DEPLOYMENT_SUCCEEDED', 'APPROVAL_REJECTED', 'LEGACY_COMPLETED')")
    op.execute("ALTER TABLE optimization_runs ADD COLUMN completion_reason run_completion_reason")
    op.execute("UPDATE optimization_runs SET completion_reason = 'LEGACY_COMPLETED' WHERE status = 'COMPLETED' AND completion_reason IS NULL")
    op.execute("ALTER TABLE optimization_runs ADD CONSTRAINT ck_completed_run_reason CHECK ((status <> 'COMPLETED') OR completion_reason IS NOT NULL)")
    op.execute("ALTER TABLE candidates ADD COLUMN source_snapshot_id uuid REFERENCES workload_snapshots(id) ON DELETE RESTRICT, ADD COLUMN source_diagnosis_id uuid REFERENCES diagnosis_artifacts(id) ON DELETE RESTRICT, ADD COLUMN deterministic_fingerprint varchar(128), ADD COLUMN generation_rule_id varchar(128), ADD COLUMN generation_rule_version varchar(64), ADD COLUMN affected_query_shape_ids json, ADD COLUMN evidence_refs json, ADD COLUMN policy_classification varchar(64)")
    op.execute("ALTER TABLE candidates ADD CONSTRAINT uq_candidate_run_fingerprint UNIQUE (optimization_run_id, deterministic_fingerprint)")
    op.execute("CREATE TABLE candidate_generation_artifacts (id uuid PRIMARY KEY, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, optimization_run_id uuid NOT NULL UNIQUE REFERENCES optimization_runs(id) ON DELETE RESTRICT, workload_snapshot_id uuid NOT NULL REFERENCES workload_snapshots(id) ON DELETE RESTRICT, diagnosis_artifact_id uuid NOT NULL REFERENCES diagnosis_artifacts(id) ON DELETE RESTRICT, generator_version varchar(64) NOT NULL, candidate_count integer NOT NULL CHECK (candidate_count >= 0), ordered_candidate_fingerprints json NOT NULL, artifact_fingerprint varchar(128) NOT NULL UNIQUE, completed_at timestamptz NOT NULL)")
    op.execute("CREATE TABLE candidate_ranking_artifacts (id uuid PRIMARY KEY, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, optimization_run_id uuid NOT NULL UNIQUE REFERENCES optimization_runs(id) ON DELETE RESTRICT, generation_artifact_id uuid NOT NULL REFERENCES candidate_generation_artifacts(id) ON DELETE RESTRICT, ai_invocation_id uuid NOT NULL REFERENCES ai_invocations(id) ON DELETE RESTRICT, ordered_candidate_ids json NOT NULL, artifact_fingerprint varchar(128) NOT NULL UNIQUE)")
    op.execute("CREATE TABLE evaluation_plans (id uuid PRIMARY KEY, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, optimization_run_id uuid NOT NULL UNIQUE REFERENCES optimization_runs(id) ON DELETE RESTRICT, ranking_artifact_id uuid NOT NULL REFERENCES candidate_ranking_artifacts(id) ON DELETE RESTRICT, profile varchar(32) NOT NULL, selected_candidate_ids json NOT NULL, calibration json NOT NULL, artifact_fingerprint varchar(128) NOT NULL UNIQUE)")
    op.execute("CREATE TABLE admission_artifacts (id uuid PRIMARY KEY, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, optimization_run_id uuid NOT NULL UNIQUE REFERENCES optimization_runs(id) ON DELETE RESTRICT, evaluation_plan_id uuid NOT NULL REFERENCES evaluation_plans(id) ON DELETE RESTRICT, selected_candidate_id uuid REFERENCES candidates(id) ON DELETE RESTRICT, admitted_candidate_ids json NOT NULL, artifact_fingerprint varchar(128) NOT NULL UNIQUE)")
    op.execute("CREATE OR REPLACE FUNCTION reject_predeployment_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'durable pre-deployment evidence is immutable'; END; $$")
    for table in ('candidate_generation_artifacts', 'candidate_ranking_artifacts', 'evaluation_plans', 'admission_artifacts', 'candidate_actions'):
        op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_predeployment_evidence_mutation()")


def downgrade() -> None:
    for table in ('candidate_actions', 'admission_artifacts', 'evaluation_plans', 'candidate_ranking_artifacts', 'candidate_generation_artifacts'):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_predeployment_evidence_mutation()")
    op.execute("DROP TABLE admission_artifacts")
    op.execute("DROP TABLE evaluation_plans")
    op.execute("DROP TABLE candidate_ranking_artifacts")
    op.execute("DROP TABLE candidate_generation_artifacts")
    op.execute("ALTER TABLE candidates DROP CONSTRAINT uq_candidate_run_fingerprint")
    op.execute("ALTER TABLE candidates DROP COLUMN policy_classification, DROP COLUMN evidence_refs, DROP COLUMN affected_query_shape_ids, DROP COLUMN generation_rule_version, DROP COLUMN generation_rule_id, DROP COLUMN deterministic_fingerprint, DROP COLUMN source_diagnosis_id, DROP COLUMN source_snapshot_id")
    op.execute("ALTER TABLE optimization_runs DROP CONSTRAINT ck_completed_run_reason")
    op.execute("ALTER TABLE optimization_runs DROP COLUMN completion_reason")
    op.execute("DROP TYPE run_completion_reason")
