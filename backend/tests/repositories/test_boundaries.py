"""Unit checks for the complete production repository boundary."""

from sqlalchemy.ext.asyncio import create_async_engine

from app.db.repositories import ControlPlaneRepositories


def test_every_required_durable_domain_has_a_postgres_repository() -> None:
    engine = create_async_engine("postgresql+asyncpg://unused")
    repositories = ControlPlaneRepositories(engine)
    required = (
        "users", "targets", "runs", "candidates", "evaluations", "admissions", "approvals",
        "ledger", "experience", "jobs", "audit", "recovery",
    )
    assert all(hasattr(repositories, name) for name in required)
    engine.sync_engine.dispose()
