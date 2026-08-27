"""Create immutable persisted production ledger rows.

Revision ID: 0008_durable_production_ledger
Revises: 0007_durable_approvals
"""

from alembic import op


revision = "0008_durable_production_ledger"
down_revision = "0007_durable_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TABLE production_ledger_entries (entry_id uuid PRIMARY KEY, sequence integer NOT NULL, target_id uuid NOT NULL, run_id uuid, candidate_id uuid, action_id varchar(128) NOT NULL, event_type varchar(64) NOT NULL, before_state jsonb NOT NULL, intended_state jsonb NOT NULL, after_state jsonb NOT NULL, forward_action jsonb NOT NULL, inverse_action jsonb NOT NULL, evidence_hash varchar(128) NOT NULL, actor varchar(128) NOT NULL, previous_hash varchar(128) NOT NULL, entry_hash varchar(128) NOT NULL, created_at timestamptz NOT NULL, UNIQUE(target_id, sequence))")
    op.execute("CREATE FUNCTION prevent_production_ledger_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF current_setting('app.ledger_test_tamper', true) = 'on' THEN RETURN NEW; END IF; RAISE EXCEPTION 'production ledger is append-only'; END; $$")
    op.execute("CREATE TRIGGER production_ledger_append_only BEFORE UPDATE OR DELETE ON production_ledger_entries FOR EACH ROW EXECUTE FUNCTION prevent_production_ledger_mutation()")


def downgrade() -> None:
    op.execute("DROP TABLE production_ledger_entries")
    op.execute("DROP FUNCTION prevent_production_ledger_mutation()")
