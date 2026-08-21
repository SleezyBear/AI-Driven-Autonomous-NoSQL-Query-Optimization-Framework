"""Phase 49 controlled-crash tests for every lifecycle checkpoint."""

import pytest

from app.recovery.crash import CrashPoint, CrashRecoveryCoordinator, InjectedCrash, RecoveryJournal


@pytest.mark.parametrize("point", tuple(CrashPoint), ids=lambda point: point.value)
def test_every_required_lifecycle_crash_point_is_injected_and_recoverable(point: CrashPoint) -> None:
    journal = RecoveryJournal()
    crashing = CrashRecoveryCoordinator(journal, inject_at=point)

    with pytest.raises(InjectedCrash, match=point.value):
        crashing.checkpoint(point)

    CrashRecoveryCoordinator(journal).checkpoint(point)
    assert journal.checkpoints == [point, point]


@pytest.mark.parametrize("point", (CrashPoint.AFTER_PRODUCTION_MUTATION, CrashPoint.BEFORE_LEDGER_COMPLETION))
def test_crash_after_a_production_effect_never_replays_the_mutation(point: CrashPoint) -> None:
    journal = RecoveryJournal()
    effects: list[str] = []

    def target_state_has_effect() -> bool:
        return bool(effects)

    with pytest.raises(InjectedCrash, match=point.value):
        CrashRecoveryCoordinator(journal, inject_at=point).recover_production_mutation("action-1", target_state_has_effect, lambda: effects.append("created"))

    recovered = CrashRecoveryCoordinator(journal).recover_production_mutation("action-1", target_state_has_effect, lambda: effects.append("created"))
    repeated = CrashRecoveryCoordinator(journal).recover_production_mutation("action-1", target_state_has_effect, lambda: effects.append("created"))

    assert effects == ["created"]
    assert recovered is True
    assert repeated is False
    assert journal.completed_production_actions == {"action-1"}


def test_crash_before_a_production_mutation_applies_once_on_recovery() -> None:
    journal = RecoveryJournal()
    effects: list[str] = []

    with pytest.raises(InjectedCrash, match=CrashPoint.BEFORE_PRODUCTION_MUTATION.value):
        CrashRecoveryCoordinator(journal, inject_at=CrashPoint.BEFORE_PRODUCTION_MUTATION).recover_production_mutation("action-1", lambda: bool(effects), lambda: effects.append("created"))

    CrashRecoveryCoordinator(journal).recover_production_mutation("action-1", lambda: bool(effects), lambda: effects.append("created"))
    assert effects == ["created"]
