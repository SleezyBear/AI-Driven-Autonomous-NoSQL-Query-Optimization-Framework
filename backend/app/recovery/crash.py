"""Phase 49 crash checkpoints and state-aware production mutation recovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class CrashPoint(str, Enum):
    """Every lifecycle boundary at which recovery is explicitly exercised."""

    BEFORE_CANDIDATE_APPLICATION = "BEFORE_CANDIDATE_APPLICATION"
    AFTER_SANDBOX_APPLICATION = "AFTER_SANDBOX_APPLICATION"
    DURING_BENCHMARK = "DURING_BENCHMARK"
    AFTER_ADMISSION = "AFTER_ADMISSION"
    AFTER_APPROVAL = "AFTER_APPROVAL"
    BEFORE_PRODUCTION_MUTATION = "BEFORE_PRODUCTION_MUTATION"
    AFTER_PRODUCTION_MUTATION = "AFTER_PRODUCTION_MUTATION"
    BEFORE_LEDGER_COMPLETION = "BEFORE_LEDGER_COMPLETION"
    DURING_MONITORING = "DURING_MONITORING"
    DURING_ROLLBACK = "DURING_ROLLBACK"


class InjectedCrash(RuntimeError):
    """Controlled test crash; it is never raised by ordinary production operation."""


@dataclass
class RecoveryJournal:
    """Minimal durable-intent model retained across a worker restart in the recovery test."""

    checkpoints: list[CrashPoint] = field(default_factory=list)
    completed_production_actions: set[str] = field(default_factory=set)


class CrashRecoveryCoordinator:
    """Inject lifecycle crashes and recover production changes by observing current state."""

    def __init__(self, journal: RecoveryJournal, inject_at: CrashPoint | None = None) -> None:
        self._journal = journal
        self._inject_at = inject_at

    def checkpoint(self, point: CrashPoint) -> None:
        """Record a boundary and optionally inject the configured controlled crash."""
        self._journal.checkpoints.append(point)
        if point is self._inject_at:
            raise InjectedCrash(f"injected crash at {point.value}")

    def recover_production_mutation(
        self,
        action_id: str,
        target_state_has_effect: Callable[[], bool],
        apply_mutation: Callable[[], None],
    ) -> bool:
        """Apply at most once; after a crash, observed target state is authoritative."""
        if action_id in self._journal.completed_production_actions:
            return False
        self.checkpoint(CrashPoint.BEFORE_PRODUCTION_MUTATION)
        if not target_state_has_effect():
            apply_mutation()
        self.checkpoint(CrashPoint.AFTER_PRODUCTION_MUTATION)
        self.checkpoint(CrashPoint.BEFORE_LEDGER_COMPLETION)
        self._journal.completed_production_actions.add(action_id)
        return True
