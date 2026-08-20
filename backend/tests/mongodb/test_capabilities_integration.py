"""Live capability discovery test for the local MongoDB 8 monitored replica set."""

from __future__ import annotations

import asyncio
import os

import pytest
from pymongo import AsyncMongoClient

from app.mongodb.capabilities import MongoCapabilityCollector, MongoTopology


MONGODB_URI = os.environ.get(
    "MONITORED_MONGODB_URI",
    "mongodb://optimizer_observer:observer_dev_only@127.0.0.1:27017/admin?authSource=admin&directConnection=true",
)


@pytest.mark.asyncio
async def test_collects_capabilities_from_local_mongodb_8() -> None:
    client: AsyncMongoClient[object] = AsyncMongoClient(MONGODB_URI, serverSelectionTimeoutMS=5_000)
    try:
        capabilities = await MongoCapabilityCollector(client).collect()
    finally:
        await asyncio.wait_for(client.close(), timeout=2.0)

    assert capabilities.server_version.startswith("8.")
    assert capabilities.topology is MongoTopology.REPLICA_SET
    assert capabilities.replica_set_name == "rs-monitored"
    assert capabilities.feature_compatibility_version is not None
    assert capabilities.profiler_status is not None
    assert isinstance(capabilities.query_settings_supported, bool)
    assert isinstance(capabilities.query_stats_supported, bool)
    assert isinstance(capabilities.permissions, tuple)
