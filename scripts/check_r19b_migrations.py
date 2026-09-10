"""Exercise R19B migration paths only against newly-created disposable databases."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass
from uuid import uuid4

import asyncpg


ADMIN_URL = "postgresql://control_plane:control_plane_dev_only@127.0.0.1:5432/postgres"
DATABASE_URL = "postgresql://control_plane:control_plane_dev_only@127.0.0.1:5432/{database}"
ALEMBIC = ("-m", "alembic", "-c", "backend/alembic.ini")
REVISION_0010 = "0010_durable_pgvector_experience"
REVISION_0011 = "0011_optimization_run_lifecycle"
EXPECTED_STATES = [
    "CREATED", "SNAPSHOTTING", "DIAGNOSING", "GENERATING_CANDIDATES", "RANKING",
    "CALIBRATING", "EVALUATING", "ADMISSION", "ADMITTED", "APPROVAL_PENDING",
    "APPROVED", "DEPLOYING", "DEPLOYED", "MONITORING", "COMPLETED", "ROLLED_BACK",
    "ROLLBACK_BLOCKED", "FAILED",
]


@dataclass(frozen=True)
class LegacyRows:
    user_id: str
    target_id: str
    snapshot_id: str
    run_ids: dict[str, str]
    timestamps: dict[str, tuple]


def url(database: str) -> str:
    return DATABASE_URL.format(database=database)


def alembic_url(database: str) -> str:
    return url(database).replace("postgresql://", "postgresql+asyncpg://", 1)


def migrate(database: str, command: str, revision: str) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "DATABASE_URL": alembic_url(database)}
    return subprocess.run(
        [sys.executable, *ALEMBIC, command, revision],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


async def create_database(database: str) -> None:
    connection = await asyncpg.connect(ADMIN_URL)
    try:
        await connection.execute(f'CREATE DATABASE "{database}"')
    finally:
        await connection.close()


async def drop_database(database: str) -> None:
    connection = await asyncpg.connect(ADMIN_URL)
    try:
        await connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database,
        )
        await connection.execute(f'DROP DATABASE IF EXISTS "{database}"')
    finally:
        await connection.close()


async def version(database: str) -> str:
    connection = await asyncpg.connect(url(database))
    try:
        return await connection.fetchval("SELECT version_num FROM alembic_version")
    finally:
        await connection.close()


async def seed_legacy(database: str, statuses: tuple[str, ...]) -> LegacyRows:
    connection = await asyncpg.connect(url(database))
    marker = uuid4().hex
    try:
        user_id = await connection.fetchval(
            "INSERT INTO users (id, created_at, updated_at, email, password_hash, role, status, failed_login_count) "
            "VALUES (gen_random_uuid(), now(), now(), $1, 'hash', 'OPERATOR', 'ACTIVE', 0) RETURNING id",
            f"{marker}@example.test",
        )
        target_id = await connection.fetchval(
            "INSERT INTO targets (id, created_at, updated_at, owner_user_id, name, deployment_mode, state, connection_label, is_active) "
            "VALUES (gen_random_uuid(), now(), now(), $1, $2, 'APPROVAL_CONTROLLED', 'ACTIVE', 'r19b', true) RETURNING id",
            user_id,
            marker,
        )
        window_id = await connection.fetchval(
            "INSERT INTO telemetry_windows (id, created_at, updated_at, target_id, started_at, ended_at, source, status) "
            "VALUES (gen_random_uuid(), now(), now(), $1, now(), now(), 'r19b', 'COMPLETE') RETURNING id",
            target_id,
        )
        snapshot_id = await connection.fetchval(
            "INSERT INTO workload_snapshots (id, created_at, updated_at, target_id, telemetry_window_id, snapshot, fingerprint) "
            "VALUES (gen_random_uuid(), now(), now(), $1, $2, '{}'::jsonb, $3) RETURNING id",
            target_id,
            window_id,
            marker,
        )
        run_ids: dict[str, str] = {}
        timestamps: dict[str, tuple] = {}
        for status in statuses:
            row = await connection.fetchrow(
                "INSERT INTO optimization_runs (id, created_at, updated_at, target_id, workload_snapshot_id, status, requested_by_user_id) "
                "VALUES (gen_random_uuid(), now(), now(), $1, $2, $3::run_status, $4) "
                "RETURNING id, created_at, updated_at",
                target_id,
                snapshot_id,
                status,
                user_id,
            )
            run_ids[status] = str(row["id"])
            timestamps[status] = (row["created_at"], row["updated_at"])
        return LegacyRows(str(user_id), str(target_id), str(snapshot_id), run_ids, timestamps)
    finally:
        await connection.close()


async def assert_fresh_schema(database: str) -> None:
    connection = await asyncpg.connect(url(database))
    try:
        columns = {
            row["column_name"]: row
            for row in await connection.fetch(
                "SELECT column_name, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'optimization_runs'"
            )
        }
        assert columns["workload_snapshot_id"]["is_nullable"] == "YES"
        assert "CREATED" in (columns["status"]["column_default"] or "")
        assert columns["deployment_mode"]["is_nullable"] == "NO"
        assert columns["primary_metric_key"]["is_nullable"] == "YES"
        states = [
            row["enumlabel"]
            for row in await connection.fetch(
                "SELECT enumlabel FROM pg_enum WHERE enumtypid = 'run_status'::regtype ORDER BY enumsortorder"
            )
        ]
        assert states == EXPECTED_STATES
        assert "PENDING" not in states and "RUNNING" not in states
        foreign_keys = {
            row["conname"]
            for row in await connection.fetch(
                "SELECT conname FROM pg_constraint WHERE conrelid = 'optimization_runs'::regclass AND contype = 'f'"
            )
        }
        assert {"fk_run_target", "fk_run_snapshot", "fk_run_requester"} <= foreign_keys
        index_definition = await connection.fetchval(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'uq_jobs_initial_optimization_run'"
        )
        assert index_definition is not None
        assert "WHERE" in index_definition and "optimization_run_id IS NOT NULL" in index_definition
    finally:
        await connection.close()


async def assert_legacy_upgrade(database: str, legacy: LegacyRows) -> None:
    connection = await asyncpg.connect(url(database))
    try:
        expected = {"PENDING": "CREATED", "COMPLETED": "COMPLETED", "FAILED": "FAILED"}
        for old, new in expected.items():
            row = await connection.fetchrow(
                "SELECT id, target_id, requested_by_user_id, workload_snapshot_id, created_at, updated_at, status::text, deployment_mode, primary_metric_key "
                "FROM optimization_runs WHERE id = $1::uuid",
                legacy.run_ids[old],
            )
            assert row is not None
            assert str(row["id"]) == legacy.run_ids[old]
            assert str(row["target_id"]) == legacy.target_id
            assert str(row["requested_by_user_id"]) == legacy.user_id
            assert str(row["workload_snapshot_id"]) == legacy.snapshot_id
            assert (row["created_at"], row["updated_at"]) == legacy.timestamps[old]
            assert row["status"] == new
            assert row["deployment_mode"] == "APPROVAL_CONTROLLED"
            assert row["primary_metric_key"] is None
    finally:
        await connection.close()


async def assert_safe_downgrade(database: str, legacy: LegacyRows) -> None:
    connection = await asyncpg.connect(url(database))
    try:
        expected = {"PENDING": "PENDING", "COMPLETED": "COMPLETED", "FAILED": "FAILED"}
        for old, status in expected.items():
            row = await connection.fetchrow(
                "SELECT id, target_id, requested_by_user_id, workload_snapshot_id, status::text FROM optimization_runs WHERE id = $1::uuid",
                legacy.run_ids[old],
            )
            assert row is not None
            assert str(row["id"]) == legacy.run_ids[old]
            assert str(row["target_id"]) == legacy.target_id
            assert str(row["requested_by_user_id"]) == legacy.user_id
            assert str(row["workload_snapshot_id"]) == legacy.snapshot_id
            assert row["status"] == status
    finally:
        await connection.close()


async def run() -> None:
    databases = [f"r19b_{name}_{uuid4().hex[:12]}" for name in ("fresh", "legacy", "running", "unsafe")]
    fresh, legacy_db, running_db, unsafe_db = databases
    try:
        for database in databases:
            await create_database(database)

        result = migrate(fresh, "upgrade", "head")
        assert result.returncode == 0, result.stderr
        await assert_fresh_schema(fresh)
        print("fresh migration chain and final schema: PASS")

        result = migrate(legacy_db, "upgrade", REVISION_0010)
        assert result.returncode == 0, result.stderr
        legacy = await seed_legacy(legacy_db, ("PENDING", "COMPLETED", "FAILED"))
        result = migrate(legacy_db, "upgrade", REVISION_0011)
        assert result.returncode == 0, result.stderr
        await assert_legacy_upgrade(legacy_db, legacy)
        print("legacy 0010 to 0011 mapping and data preservation: PASS")
        result = migrate(legacy_db, "downgrade", REVISION_0010)
        assert result.returncode == 0, result.stderr
        await assert_safe_downgrade(legacy_db, legacy)
        print("safe downgrade mapping and identity preservation: PASS")

        result = migrate(running_db, "upgrade", REVISION_0010)
        assert result.returncode == 0, result.stderr
        running = await seed_legacy(running_db, ("RUNNING",))
        result = migrate(running_db, "upgrade", REVISION_0011)
        assert result.returncode != 0 and "cannot migrate RUNNING" in (result.stdout + result.stderr)
        connection = await asyncpg.connect(url(running_db))
        try:
            assert await connection.fetchval("SELECT status::text FROM optimization_runs WHERE id = $1::uuid", running.run_ids["RUNNING"]) == "RUNNING"
        finally:
            await connection.close()
        assert await version(running_db) == REVISION_0010
        print("legacy RUNNING refusal before enum conversion: PASS")

        result = migrate(unsafe_db, "upgrade", REVISION_0010)
        assert result.returncode == 0, result.stderr
        unsafe = await seed_legacy(unsafe_db, ("PENDING",))
        result = migrate(unsafe_db, "upgrade", REVISION_0011)
        assert result.returncode == 0, result.stderr
        connection = await asyncpg.connect(url(unsafe_db))
        try:
            await connection.execute("UPDATE optimization_runs SET status = 'DEPLOYING'::run_status WHERE id = $1::uuid", unsafe.run_ids["PENDING"])
        finally:
            await connection.close()
        result = migrate(unsafe_db, "downgrade", REVISION_0010)
        assert result.returncode != 0 and "cannot downgrade active optimization lifecycle states safely" in (result.stdout + result.stderr)
        connection = await asyncpg.connect(url(unsafe_db))
        try:
            assert await connection.fetchval("SELECT status::text FROM optimization_runs WHERE id = $1::uuid", unsafe.run_ids["PENDING"]) == "DEPLOYING"
            await connection.execute("UPDATE optimization_runs SET status = 'MONITORING'::run_status WHERE id = $1::uuid", unsafe.run_ids["PENDING"])
        finally:
            await connection.close()
        assert await version(unsafe_db) == REVISION_0011
        result = migrate(unsafe_db, "downgrade", REVISION_0010)
        assert result.returncode != 0 and "cannot downgrade active optimization lifecycle states safely" in (result.stdout + result.stderr)
        connection = await asyncpg.connect(url(unsafe_db))
        try:
            assert await connection.fetchval("SELECT status::text FROM optimization_runs WHERE id = $1::uuid", unsafe.run_ids["PENDING"]) == "MONITORING"
        finally:
            await connection.close()
        print("unsafe active-state downgrade refusal before enum conversion: PASS")
    finally:
        for database in databases:
            await drop_database(database)


if __name__ == "__main__":
    asyncio.run(run())
