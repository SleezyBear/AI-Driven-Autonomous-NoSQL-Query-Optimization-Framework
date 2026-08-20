"""Capability discovery using PyMongo's asynchronous MongoDB client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Any, cast

from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError


class MongoTopology(str, Enum):
    """MongoDB deployment shapes relevant to optimizer safety decisions."""

    STANDALONE = "STANDALONE"
    REPLICA_SET = "REPLICA_SET"
    SHARDED = "SHARDED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MongoCapabilities:
    """A point-in-time MongoDB capability snapshot without application data."""

    server_version: str
    feature_compatibility_version: str | None
    topology: MongoTopology
    replica_set_name: str | None
    query_settings_supported: bool
    query_stats_supported: bool
    profiler_status: int | None
    permissions: tuple[str, ...]


class MongoCapabilityCollector:
    """Collect MongoDB server capabilities through fixed metadata commands only."""

    def __init__(self, client: AsyncMongoClient[Any]) -> None:
        self._client = client

    async def collect(self) -> MongoCapabilities:
        """Return an immutable capability snapshot for the configured MongoDB target."""
        build_info = await self._command("admin", {"buildInfo": 1})
        hello = await self._command("admin", {"hello": 1})
        fcv = await self._command("admin", {"getParameter": 1, "featureCompatibilityVersion": 1})
        profiler = await self._command("admin", {"profile": -1})
        connection_status = await self._command("admin", {"connectionStatus": 1, "showPrivileges": True})

        permissions = self._permissions(connection_status)
        return MongoCapabilities(
            server_version=str(build_info.get("version", "unknown")),
            feature_compatibility_version=self._fcv(fcv),
            topology=self._topology(hello),
            replica_set_name=self._optional_string(hello.get("setName")),
            query_settings_supported=await self._command_supported("admin", {"getQuerySettings": {}}),
            query_stats_supported=await self._command_supported(
                "admin", {"getParameter": 1, "internalQueryStatsRateLimit": 1}
            ),
            profiler_status=self._optional_int(profiler.get("was")),
            permissions=permissions,
        )

    async def _command(self, database_name: str, command: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await asyncio.wait_for(
                self._client.get_database(database_name).command(command), timeout=2.0
            )
        except (asyncio.TimeoutError, PyMongoError):
            return {}
        return cast(dict[str, Any], result)

    async def _command_supported(self, database_name: str, command: dict[str, Any]) -> bool:
        try:
            await asyncio.wait_for(
                self._client.get_database(database_name).command(command), timeout=2.0
            )
        except (asyncio.TimeoutError, PyMongoError):
            return False
        return True

    @staticmethod
    def _fcv(result: dict[str, Any]) -> str | None:
        value = result.get("featureCompatibilityVersion")
        if isinstance(value, dict):
            return MongoCapabilityCollector._optional_string(value.get("version"))
        return MongoCapabilityCollector._optional_string(value)

    @staticmethod
    def _topology(hello: dict[str, Any]) -> MongoTopology:
        if hello.get("msg") == "isdbgrid":
            return MongoTopology.SHARDED
        if "setName" in hello:
            return MongoTopology.REPLICA_SET
        if hello:
            return MongoTopology.STANDALONE
        return MongoTopology.UNKNOWN

    @staticmethod
    def _permissions(result: dict[str, Any]) -> tuple[str, ...]:
        auth_info = result.get("authInfo")
        if not isinstance(auth_info, dict):
            return ()
        roles = auth_info.get("authenticatedUserRoles")
        if not isinstance(roles, list):
            return ()
        values: list[str] = []
        for role in roles:
            if isinstance(role, dict) and isinstance(role.get("role"), str):
                database = role.get("db")
                suffix = f"@{database}" if isinstance(database, str) else ""
                values.append(f"{role['role']}{suffix}")
        return tuple(sorted(values))

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        return value if isinstance(value, str) else None

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        return value if isinstance(value, int) else None
