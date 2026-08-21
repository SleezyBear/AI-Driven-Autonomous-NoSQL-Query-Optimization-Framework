"""Intel-Mac default limits for expensive optimizer work."""

from __future__ import annotations

from asyncio import Semaphore
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar


T = TypeVar("T")


class HeavyTaskKind(str, Enum):
    """Heavy task categories that must not overload the development host."""

    AI_REQUEST = "AI_REQUEST"
    BENCHMARK = "BENCHMARK"
    EVALUATION = "EVALUATION"
    PRODUCTION_MUTATION = "PRODUCTION_MUTATION"


@dataclass(frozen=True)
class IntelMacResourceLimits:
    """Conservative defaults for the supported Intel macOS development environment."""

    max_parallel_ai_requests: int = 1
    max_parallel_benchmarks: int = 1
    max_parallel_evaluations: int = 1
    max_production_mutations_per_target: int = 1


class HeavyTaskLimiter:
    """Serialize controlled heavy work; production mutation limits are independent per target."""

    def __init__(self, limits: IntelMacResourceLimits = IntelMacResourceLimits()) -> None:
        self.limits = limits
        self._ai_requests = Semaphore(limits.max_parallel_ai_requests)
        self._benchmarks = Semaphore(limits.max_parallel_benchmarks)
        self._evaluations = Semaphore(limits.max_parallel_evaluations)
        self._production_mutations: dict[str, Semaphore] = {}

    @asynccontextmanager
    async def ai_request(self) -> AsyncIterator[None]:
        async with self._ai_requests:
            yield

    @asynccontextmanager
    async def benchmark(self) -> AsyncIterator[None]:
        async with self._benchmarks:
            yield

    @asynccontextmanager
    async def evaluation(self) -> AsyncIterator[None]:
        async with self._evaluations:
            yield

    @asynccontextmanager
    async def production_mutation(self, target_id: str) -> AsyncIterator[None]:
        limiter = self._production_mutations.setdefault(target_id, Semaphore(self.limits.max_production_mutations_per_target))
        async with limiter:
            yield

    async def run(self, kind: HeavyTaskKind, operation: Callable[[], Awaitable[T]], target_id: str | None = None) -> T:
        """Run one categorized operation under its required concurrency limit."""
        if kind is HeavyTaskKind.AI_REQUEST:
            async with self.ai_request():
                return await operation()
        if kind is HeavyTaskKind.BENCHMARK:
            async with self.benchmark():
                return await operation()
        if kind is HeavyTaskKind.EVALUATION:
            async with self.evaluation():
                return await operation()
        if target_id is None:
            raise ValueError("production mutation tasks require a target ID")
        async with self.production_mutation(target_id):
            return await operation()


shared_heavy_task_limiter = HeavyTaskLimiter()
