"""Add immutable authority and durable deployment artifacts for R19L-P."""

from alembic import op


revision = "0017_durable_prod_lifecycle"
down_revision = "0016_candidate_immutability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TABLE authority_decisions (id uuid PRIMARY KEY, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, optimization_run_id uuid NOT NULL UNIQUE REFERENCES optimization_runs(id) ON DELETE RESTRICT, candidate_id uuid NOT NULL REFERENCES candidates(id) ON DELETE RESTRICT, candidate_fingerprint varchar(128) NOT NULL, deployment_mode varchar(32) NOT NULL, authority_type varchar(32) NOT NULL, authority_reason varchar(128) NOT NULL, production_autonomy_eligible boolean NOT NULL, integrity_fingerprint varchar(128) NOT NULL UNIQUE)")
    op.execute("CREATE TABLE deployment_artifacts (id uuid PRIMARY KEY, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, optimization_run_id uuid NOT NULL UNIQUE REFERENCES optimization_runs(id) ON DELETE RESTRICT, candidate_id uuid NOT NULL REFERENCES candidates(id) ON DELETE RESTRICT, candidate_fingerprint varchar(128) NOT NULL, action_fingerprint varchar(128) NOT NULL, idempotency_key varchar(128) NOT NULL UNIQUE, status varchar(32) NOT NULL, before_state json NOT NULL, inverse_action json NOT NULL, after_state json)")
    op.execute("CREATE OR REPLACE FUNCTION reject_r19lp_artifact_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'R19L-P durable artifact is immutable'; END; $$")
    op.execute("CREATE TRIGGER authority_decisions_immutable BEFORE UPDATE OR DELETE ON authority_decisions FOR EACH ROW EXECUTE FUNCTION reject_r19lp_artifact_mutation()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS authority_decisions_immutable ON authority_decisions")
    op.execute("DROP FUNCTION IF EXISTS reject_r19lp_artifact_mutation()")
    op.execute("DROP TABLE deployment_artifacts")
    op.execute("DROP TABLE authority_decisions")
