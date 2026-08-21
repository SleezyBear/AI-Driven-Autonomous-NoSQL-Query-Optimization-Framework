"""Phase 50 tests for default heavy-task concurrency protection."""

import asyncio
from typing import cast

import pytest

from app.resources.protection import HeavyTaskKind, HeavyTaskLimiter, IntelMacResourceLimits
from app.worker.durable import DurableJobWorker, JobRepository


def test_intel_mac_defaults_match_the_required_single_task_limits() -> None:
    assert IntelMacResourceLimits() == IntelMacResourceLimits(1, 1, 1, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", (HeavyTaskKind.AI_REQUEST, HeavyTaskKind.BENCHMARK, HeavyTaskKind.EVALUATION))
async def test_heavy_categories_run_one_at_a_time_by_default(kind: HeavyTaskKind) -> None:
    limiter = HeavyTaskLimiter()
    active = 0
    maximum = 0

    async def operation() -> None:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1

    await asyncio.gather(*(limiter.run(kind, operation) for _ in range(4)))
    assert maximum == 1


@pytest.mark.asyncio
async def test_worker_limits_production_mutations_per_target_but_not_across_targets() -> None:
    limiter = HeavyTaskLimiter()
    worker = DurableJobWorker(cast(JobRepository, object()), "worker-a", limiter)
    active_by_target: dict[str, int] = {"a": 0, "b": 0}
    maximum_by_target: dict[str, int] = {"a": 0, "b": 0}

    def operation(target_id: str):
        async def run() -> None:
            active_by_target[target_id] += 1
            maximum_by_target[target_id] = max(maximum_by_target[target_id], active_by_target[target_id])
            await asyncio.sleep(0)
            active_by_target[target_id] -= 1

        return run

    await asyncio.gather(
        worker.run_heavy_task(HeavyTaskKind.PRODUCTION_MUTATION, operation("a"), "a"),
        worker.run_heavy_task(HeavyTaskKind.PRODUCTION_MUTATION, operation("a"), "a"),
        worker.run_heavy_task(HeavyTaskKind.PRODUCTION_MUTATION, operation("b"), "b"),
    )
    assert maximum_by_target == {"a": 1, "b": 1}


@pytest.mark.asyncio
async def test_production_mutation_requires_target_identity() -> None:
    with pytest.raises(ValueError, match="target ID"):
        await HeavyTaskLimiter().run(HeavyTaskKind.PRODUCTION_MUTATION, _noop)


async def _noop() -> None:
    return None
