"""Deployment-wide PostgreSQL advisory locks for one target mutation at a time."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


def target_lock_key(target_id: str | UUID) -> int:
    """Derive the signed 64-bit PostgreSQL advisory-lock identity solely from target_id."""
    raw = hashlib.sha256(str(target_id).encode("utf-8")).digest()[:8]
    return int.from_bytes(raw, byteorder="big", signed=True)


@dataclass
class TargetMutationLease:
    """A session-scoped lock lease that must be released after the mutation."""

    connection: AsyncConnection
    key: int

    async def release(self) -> None:
        await self.connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self.key})
        await self.connection.close()


class PostgresTargetMutationLock:
    """The production authority for target mutation exclusion across all workers."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def try_acquire(self, target_id: str | UUID) -> TargetMutationLease | None:
        key = target_lock_key(target_id)
        connection = await self._engine.connect()
        acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        if acquired is not True:
            await connection.close()
            return None
        return TargetMutationLease(connection, key)
