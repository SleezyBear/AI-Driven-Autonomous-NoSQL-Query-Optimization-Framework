"""R6 acceptance: independent worker connections cannot mutate one target together."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.db.runtime import create_control_plane_engine
from app.production.target_lock import PostgresTargetMutationLock, target_lock_key


@pytest.mark.asyncio
async def test_two_independent_workers_only_one_obtains_target_authority() -> None:
    target_id = uuid4()
    engine_a = create_control_plane_engine()
    engine_b = create_control_plane_engine()
    worker_a = PostgresTargetMutationLock(engine_a)
    worker_b = PostgresTargetMutationLock(engine_b)
    first, second = await asyncio.gather(worker_a.try_acquire(target_id), worker_b.try_acquire(target_id))
    leases = [lease for lease in (first, second) if lease is not None]
    assert len(leases) == 1
    assert await (worker_b if first is not None else worker_a).try_acquire(target_id) is None
    await leases[0].release()
    recovered = await (worker_b if first is not None else worker_a).try_acquire(target_id)
    assert recovered is not None
    await recovered.release()
    await engine_a.dispose()
    await engine_b.dispose()


def test_lock_identity_is_only_a_stable_target_identifier() -> None:
    target_id = uuid4()
    assert target_lock_key(target_id) == target_lock_key(str(target_id))
    assert target_lock_key(target_id) != target_lock_key(uuid4())
