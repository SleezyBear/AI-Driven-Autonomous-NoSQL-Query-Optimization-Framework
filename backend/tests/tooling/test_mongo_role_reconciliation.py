"""Static checks that MongoDB optimizer roles are reconciled, not frozen.

A retained Mongo volume must converge to the declared role privileges, so the
initialization script must create roles when absent and update them when
present.  The executor privilege boundary must stay read/index-only.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INIT_SCRIPT = (ROOT / "infra/mongo/init-replica-set.sh").read_text(encoding="utf-8")


def test_initialization_reconciles_both_optimizer_roles() -> None:
    assert "admin.createRole" in INIT_SCRIPT
    for role in ("optimizerObserver", "optimizerExecutor"):
        assert f'role: "{role}"' in INIT_SCRIPT
        assert f'admin.updateRole("{role}"' in INIT_SCRIPT


def test_executor_is_granted_query_settings_in_the_declared_privileges() -> None:
    assert '"querySettings"' in INIT_SCRIPT


def test_executor_cannot_write_application_documents() -> None:
    # Role privileges must never grant document writes or destructive DDL.
    for forbidden in ('"insert"', '"update"', '"remove"', '"delete"', '"dropDatabase"', '"dropCollection"'):
        assert forbidden not in INIT_SCRIPT, f"optimizer executor must not be granted {forbidden}"


def test_observer_is_not_broadened_by_reconciliation() -> None:
    # The observer is reconciled to its existing declared set and never gains
    # index or query-settings actions.
    observer_block = INIT_SCRIPT.split("const executorPrivileges", 1)[0]
    assert '"querySettings"' not in observer_block
    assert '"createIndex"' not in observer_block
    assert '"dropIndex"' not in observer_block
