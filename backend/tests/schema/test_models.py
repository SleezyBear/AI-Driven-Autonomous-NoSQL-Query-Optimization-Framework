"""Unit coverage for the R2 SQLAlchemy model registry."""

from app.db.models import Base


def test_control_plane_models_cover_every_durable_domain() -> None:
    required = {
        "users", "targets", "target_credentials", "evaluation_mappings", "capability_snapshots",
        "namespaces", "query_shapes", "telemetry_windows", "metric_observations", "workload_snapshots",
        "optimization_runs", "candidates", "candidate_actions", "evaluation_runs", "trial_pairs",
        "trial_metrics", "admission_decisions", "safety_results", "approval_requests", "approval_decisions",
        "ledger_entries", "rollback_records", "experience_records", "jobs", "audit_events", "settings",
    }
    assert required <= set(Base.metadata.tables)
    assert all(Base.metadata.tables[name].c.id.type.__class__.__name__.lower() == "uuid" for name in required)
