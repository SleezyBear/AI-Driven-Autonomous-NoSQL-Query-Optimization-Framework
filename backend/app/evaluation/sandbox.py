"""Evaluate typed index candidates only against an isolated evaluation target."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Protocol

from app.actions.schemas import CreateIndexAction
from app.adapters.contracts import DatabaseAdapter, IndexSpec, Namespace
from app.isolation.lock import BenchmarkOllamaIsolationLock, shared_measurement_lock


class SandboxStatus(str, Enum):
    COMPLETED = "COMPLETED"
    REJECTED_TARGET_SEPARATION = "REJECTED_TARGET_SEPARATION"
    REJECTED_RESOURCE_BUDGET = "REJECTED_RESOURCE_BUDGET"
    INVALID_EVALUATION_STATE = "INVALID_EVALUATION_STATE"
    FAILED = "FAILED"


@dataclass(frozen=True)
class EvaluationState:
    """Verified copied-state evidence, excluding credentials and application documents."""

    source_dataset_fingerprint: str
    evaluation_dataset_fingerprint: str
    source_topology_identity: str
    evaluation_topology_identity: str
    free_disk_bytes: int


@dataclass(frozen=True)
class ResourceBudget:
    """Caller-declared index-storage and required-free-disk constraints."""

    maximum_index_bytes: int
    minimum_free_disk_bytes: int


@dataclass(frozen=True)
class SandboxResult:
    status: SandboxStatus
    benchmark_result: str | None = None
    admission_result: str | None = None
    reason: str | None = None


class EvaluationStateCopier(Protocol):
    """Copy monitored state to the separate evaluation target and return verification facts."""

    async def copy_and_verify(self, monitored_target_id: str, evaluation_target_id: str) -> EvaluationState:
        """Copy and verify the isolated target before candidate application."""


class SandboxIndexEvaluator:
    """Apply, benchmark, admit, and always clean up a candidate only in evaluation."""

    def __init__(self, state_copier: EvaluationStateCopier, evaluation_adapter: DatabaseAdapter, isolation_lock: BenchmarkOllamaIsolationLock = shared_measurement_lock) -> None:
        self._state_copier = state_copier
        self._evaluation_adapter = evaluation_adapter
        self._isolation_lock = isolation_lock

    async def evaluate(
        self,
        monitored_target_id: str,
        evaluation_target_id: str,
        candidate: CreateIndexAction,
        budget: ResourceBudget,
        estimate_index_bytes: Callable[[CreateIndexAction], int],
        benchmark: Callable[[], Awaitable[str]],
        admit: Callable[[str], str],
    ) -> SandboxResult:
        """Execute copy → verify → apply → benchmark → admission → cleanup in evaluation only."""
        if monitored_target_id == evaluation_target_id:
            return SandboxResult(SandboxStatus.REJECTED_TARGET_SEPARATION, reason="target IDs must differ")
        state = await self._state_copier.copy_and_verify(monitored_target_id, evaluation_target_id)
        if (
            state.source_dataset_fingerprint != state.evaluation_dataset_fingerprint
            or state.source_topology_identity == state.evaluation_topology_identity
        ):
            return SandboxResult(SandboxStatus.INVALID_EVALUATION_STATE, reason="evaluation state is not isolated and equivalent")
        estimated_bytes = estimate_index_bytes(candidate)
        if estimated_bytes < 0 or estimated_bytes > budget.maximum_index_bytes or state.free_disk_bytes - estimated_bytes < budget.minimum_free_disk_bytes:
            return SandboxResult(SandboxStatus.REJECTED_RESOURCE_BUDGET, reason="index storage or disk headroom budget exceeded")
        namespace = Namespace(collection=candidate.collection)
        index = IndexSpec(name=candidate.index_name, keys=tuple((field.field, field.direction) for field in candidate.fields))
        applied = False
        try:
            await self._evaluation_adapter.create_index(namespace, index)
            applied = True
            async with self._isolation_lock.benchmark_window():
                benchmark_result = await benchmark()
            return SandboxResult(SandboxStatus.COMPLETED, benchmark_result, admit(benchmark_result))
        except Exception:
            return SandboxResult(SandboxStatus.FAILED, reason="sandbox evaluation failed")
        finally:
            if applied:
                await self._evaluation_adapter.drop_index(namespace, candidate.index_name)
