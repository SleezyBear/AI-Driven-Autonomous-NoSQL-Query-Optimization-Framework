"""Exit a real process at an owned Mongo deployment boundary for R24 recovery."""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any
from uuid import UUID

from pymongo import AsyncMongoClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.adapters.contracts import DatabaseAdapter, IndexSpec, Namespace, QuerySettingsIndexHint
from app.adapters.mongodb import MongoDBAdapter
from app.production.durable import DurableDeploymentService
from app.rollback.durable import DurableRollbackService
from app.worker.durable import ExecutionContext


class ProcessExitAdapter(DatabaseAdapter):
    def __init__(self, delegate: DatabaseAdapter, boundary: str) -> None:
        self._delegate = delegate
        self._boundary = boundary

    async def list_namespaces(self) -> tuple[Namespace, ...]:
        return await self._delegate.list_namespaces()

    async def list_indexes(self, namespace: Namespace) -> tuple[IndexSpec, ...]:
        return await self._delegate.list_indexes(namespace)

    async def create_index(self, namespace: Namespace, index: IndexSpec) -> None:
        if self._boundary == "before_mutation":
            os._exit(73)
        await self._delegate.create_index(namespace, index)
        if self._boundary == "after_mutation":
            os._exit(74)

    async def drop_index(self, namespace: Namespace, index_name: str) -> None:
        await self._delegate.drop_index(namespace, index_name)
        if self._boundary == "rollback_after_mutation":
            os._exit(75)

    async def get_query_settings_index_hint(
        self, namespace: Namespace, query_shape_hash: str
    ) -> QuerySettingsIndexHint | None:
        return await self._delegate.get_query_settings_index_hint(namespace, query_shape_hash)

    async def set_query_settings_index_hint(
        self,
        namespace: Namespace,
        query_shape_hash: str,
        hint: QuerySettingsIndexHint | None,
    ) -> None:
        await self._delegate.set_query_settings_index_hint(namespace, query_shape_hash, hint)


async def main(run_id: UUID, boundary: str) -> None:
    database_url = os.environ["DATABASE_URL"]
    mongo_uri = os.environ["R24_MONGO_EXECUTOR_URI"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    mongo: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(mongo_uri)
    try:
        adapter = ProcessExitAdapter(MongoDBAdapter(mongo, "commerce"), boundary)
        if boundary == "rollback_after_mutation":
            await DurableRollbackService(engine, adapter).rollback_for_run(run_id)
        else:
            await DurableDeploymentService(engine, adapter).deploy_for_run(
                run_id, ExecutionContext(asyncio.Event())
            )
    finally:
        await mongo.close()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", type=UUID)
    parser.add_argument(
        "boundary",
        choices=("before_mutation", "after_mutation", "rollback_after_mutation"),
    )
    arguments = parser.parse_args()
    asyncio.run(main(arguments.run_id, arguments.boundary))
