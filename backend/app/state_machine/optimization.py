"""Frozen lifecycle transitions for one optimization request."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class OptimizationState(str, Enum):
    """Every permitted state in the optimization lifecycle."""

    CREATED = "CREATED"
    SNAPSHOTTING = "SNAPSHOTTING"
    DIAGNOSING = "DIAGNOSING"
    GENERATING_CANDIDATES = "GENERATING_CANDIDATES"
    RANKING = "RANKING"
    CALIBRATING = "CALIBRATING"
    EVALUATING = "EVALUATING"
    ADMISSION = "ADMISSION"
    ADMITTED = "ADMITTED"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    DEPLOYING = "DEPLOYING"
    DEPLOYED = "DEPLOYED"
    MONITORING = "MONITORING"
    COMPLETED = "COMPLETED"
    ROLLED_BACK = "ROLLED_BACK"
    ROLLBACK_BLOCKED = "ROLLBACK_BLOCKED"
    FAILED = "FAILED"


class InvalidStateTransition(ValueError):
    """Raised when a requested lifecycle transition is not explicitly allowed."""


_NEXT_STATES: dict[OptimizationState, frozenset[OptimizationState]] = {
    OptimizationState.CREATED: frozenset({OptimizationState.SNAPSHOTTING, OptimizationState.FAILED}),
    OptimizationState.SNAPSHOTTING: frozenset({OptimizationState.DIAGNOSING, OptimizationState.FAILED}),
    OptimizationState.DIAGNOSING: frozenset({OptimizationState.GENERATING_CANDIDATES, OptimizationState.FAILED}),
    OptimizationState.GENERATING_CANDIDATES: frozenset({OptimizationState.RANKING, OptimizationState.FAILED}),
    OptimizationState.RANKING: frozenset({OptimizationState.CALIBRATING, OptimizationState.FAILED}),
    OptimizationState.CALIBRATING: frozenset({OptimizationState.EVALUATING, OptimizationState.FAILED}),
    OptimizationState.EVALUATING: frozenset({OptimizationState.ADMISSION, OptimizationState.FAILED}),
    OptimizationState.ADMISSION: frozenset({OptimizationState.ADMITTED, OptimizationState.FAILED}),
    OptimizationState.ADMITTED: frozenset({OptimizationState.APPROVAL_PENDING, OptimizationState.FAILED}),
    OptimizationState.APPROVAL_PENDING: frozenset({OptimizationState.APPROVED, OptimizationState.FAILED}),
    OptimizationState.APPROVED: frozenset({OptimizationState.DEPLOYING, OptimizationState.FAILED}),
    OptimizationState.DEPLOYING: frozenset({OptimizationState.DEPLOYED, OptimizationState.FAILED}),
    OptimizationState.DEPLOYED: frozenset(
        {OptimizationState.MONITORING, OptimizationState.ROLLED_BACK, OptimizationState.ROLLBACK_BLOCKED, OptimizationState.FAILED}
    ),
    OptimizationState.MONITORING: frozenset(
        {OptimizationState.COMPLETED, OptimizationState.ROLLED_BACK, OptimizationState.ROLLBACK_BLOCKED, OptimizationState.FAILED}
    ),
    OptimizationState.COMPLETED: frozenset(),
    OptimizationState.ROLLED_BACK: frozenset(),
    OptimizationState.ROLLBACK_BLOCKED: frozenset(),
    OptimizationState.FAILED: frozenset(),
}


@dataclass
class OptimizationStateMachine:
    """Enforce the declared lifecycle and retain an immutable-view transition history."""

    state: OptimizationState = OptimizationState.CREATED
    _history: list[OptimizationState] = field(default_factory=lambda: [OptimizationState.CREATED])

    @property
    def history(self) -> tuple[OptimizationState, ...]:
        """Return the lifecycle states in transition order, including the initial state."""
        return tuple(self._history)

    def transition(self, next_state: OptimizationState) -> OptimizationState:
        """Move to an explicitly allowed next state or fail without changing state."""
        if next_state not in _NEXT_STATES[self.state]:
            raise InvalidStateTransition(f"cannot transition from {self.state.value} to {next_state.value}")
        self.state = next_state
        self._history.append(next_state)
        return self.state
