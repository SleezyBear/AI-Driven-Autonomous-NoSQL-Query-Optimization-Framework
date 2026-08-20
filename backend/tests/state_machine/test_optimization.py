"""Phase 25 acceptance tests for optimization lifecycle transitions."""

import pytest

from app.state_machine.optimization import (
    InvalidStateTransition,
    OptimizationState,
    OptimizationStateMachine,
)


def test_full_optimization_lifecycle_reaches_completed() -> None:
    machine = OptimizationStateMachine()
    for state in (
        OptimizationState.SNAPSHOTTING,
        OptimizationState.DIAGNOSING,
        OptimizationState.GENERATING_CANDIDATES,
        OptimizationState.RANKING,
        OptimizationState.CALIBRATING,
        OptimizationState.EVALUATING,
        OptimizationState.ADMISSION,
        OptimizationState.ADMITTED,
        OptimizationState.APPROVAL_PENDING,
        OptimizationState.APPROVED,
        OptimizationState.DEPLOYING,
        OptimizationState.DEPLOYED,
        OptimizationState.MONITORING,
        OptimizationState.COMPLETED,
    ):
        machine.transition(state)

    assert machine.state is OptimizationState.COMPLETED
    assert machine.history[0] is OptimizationState.CREATED
    assert machine.history[-1] is OptimizationState.COMPLETED


def test_invalid_transition_fails_without_mutating_state() -> None:
    machine = OptimizationStateMachine()

    with pytest.raises(InvalidStateTransition, match="CREATED to DEPLOYING"):
        machine.transition(OptimizationState.DEPLOYING)

    assert machine.state is OptimizationState.CREATED
    assert machine.history == (OptimizationState.CREATED,)


@pytest.mark.parametrize("terminal_state", [OptimizationState.ROLLED_BACK, OptimizationState.ROLLBACK_BLOCKED])
def test_deployment_recovery_states_are_terminal(terminal_state: OptimizationState) -> None:
    machine = OptimizationStateMachine()
    for state in (
        OptimizationState.SNAPSHOTTING,
        OptimizationState.DIAGNOSING,
        OptimizationState.GENERATING_CANDIDATES,
        OptimizationState.RANKING,
        OptimizationState.CALIBRATING,
        OptimizationState.EVALUATING,
        OptimizationState.ADMISSION,
        OptimizationState.ADMITTED,
        OptimizationState.APPROVAL_PENDING,
        OptimizationState.APPROVED,
        OptimizationState.DEPLOYING,
        OptimizationState.DEPLOYED,
        terminal_state,
    ):
        machine.transition(state)

    with pytest.raises(InvalidStateTransition):
        machine.transition(OptimizationState.MONITORING)
