"""R19C unit coverage for typed optimization dispatch safety boundaries."""

import asyncio

import pytest

from app.db import models
from app.worker.durable import ExecutionContext, Job, JobRepository, LeaseLostError, PermanentJobError
from app.worker.service import JobDispatcher, OptimizationJobHandler


class _Runs:
    def __init__(self, run: object) -> None:
        self.run = run

    async def get(self, _run_id: str) -> object:
        return self.run


class _Repositories:
    def __init__(self, run: object) -> None:
        self.runs = _Runs(run)


@pytest.mark.asyncio
async def test_dispatcher_fails_closed_for_unknown_kind_and_id_mismatch() -> None:
    dispatcher = JobDispatcher(OptimizationJobHandler(_Repositories({"status": models.RunStatus.CREATED})))
    with pytest.raises(PermanentJobError, match="UNKNOWN_JOB_KIND"):
        await dispatcher.dispatch(Job("j", "r", "UNKNOWN", {}, 1), ExecutionContext(asyncio.Event()))
    with pytest.raises(PermanentJobError, match="JOB_RUN_ID_MISMATCH"):
        await dispatcher.dispatch(Job("j", "r", "OPTIMIZATION", {"run_id": "other"}, 1), ExecutionContext(asyncio.Event()))


@pytest.mark.asyncio
async def test_terminal_run_is_idempotent_and_nonterminal_requires_real_orchestrator() -> None:
    terminal = JobDispatcher(OptimizationJobHandler(_Repositories({"status": models.RunStatus.COMPLETED})))
    await terminal.dispatch(Job("j", "r", "OPTIMIZATION", {"run_id": "r"}, 1), ExecutionContext(asyncio.Event()))
    active = JobDispatcher(OptimizationJobHandler(_Repositories({"status": models.RunStatus.CREATED})))
    with pytest.raises(PermanentJobError, match="DURABLE_ORCHESTRATOR_REQUIRED"):
        await active.dispatch(Job("j", "r", "OPTIMIZATION", {"run_id": "r"}, 1), ExecutionContext(asyncio.Event()))


def test_backoff_and_checkpoint_fail_closed() -> None:
    assert [JobRepository.backoff_seconds(attempt) for attempt in range(1, 7)] == [1, 2, 4, 8, 16, 16]
    lost = asyncio.Event()
    context = ExecutionContext(lost)
    context.ensure_lease_owned()
    lost.set()
    with pytest.raises(LeaseLostError):
        context.ensure_lease_owned()
