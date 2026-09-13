"""Protect generated candidate definitions while allowing later status evidence."""

from alembic import op


revision = "0016_candidate_immutability"
down_revision = "0015_predeployment_orchestration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE OR REPLACE FUNCTION reject_candidate_definition_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF OLD.optimization_run_id IS DISTINCT FROM NEW.optimization_run_id OR OLD.query_shape_id IS DISTINCT FROM NEW.query_shape_id OR OLD.candidate_hash IS DISTINCT FROM NEW.candidate_hash OR OLD.source_snapshot_id IS DISTINCT FROM NEW.source_snapshot_id OR OLD.source_diagnosis_id IS DISTINCT FROM NEW.source_diagnosis_id OR OLD.deterministic_fingerprint IS DISTINCT FROM NEW.deterministic_fingerprint OR OLD.generation_rule_id IS DISTINCT FROM NEW.generation_rule_id OR OLD.generation_rule_version IS DISTINCT FROM NEW.generation_rule_version OR OLD.affected_query_shape_ids IS DISTINCT FROM NEW.affected_query_shape_ids OR OLD.evidence_refs IS DISTINCT FROM NEW.evidence_refs OR OLD.policy_classification IS DISTINCT FROM NEW.policy_classification THEN RAISE EXCEPTION 'candidate definition is immutable after generation'; END IF; RETURN NEW; END; $$")
    op.execute("CREATE TRIGGER candidates_definition_immutable BEFORE UPDATE ON candidates FOR EACH ROW EXECUTE FUNCTION reject_candidate_definition_mutation()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS candidates_definition_immutable ON candidates")
    op.execute("DROP FUNCTION IF EXISTS reject_candidate_definition_mutation()")
