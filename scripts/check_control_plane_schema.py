"""Exercise the R2 control-plane schema on a disposable PostgreSQL database."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from uuid import uuid4

import asyncpg
from alembic import command
from alembic.config import Config


ROOT = Path(__file__).resolve().parents[1]
ADMIN_URL = "postgresql://control_plane:control_plane_dev_only@127.0.0.1:5432/postgres"
DATABASE_URL = "postgresql+asyncpg://control_plane:control_plane_dev_only@127.0.0.1:5432/{database}"


def migration_contract() -> object:
    path = ROOT / "backend" / "alembic" / "versions" / "0004_real_control_plane_schema.py"
    specification = importlib.util.spec_from_file_location("r2_schema", path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def alembic_config(database: str) -> Config:
    config = Config(str(ROOT / "backend" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", DATABASE_URL.format(database=database))
    return config


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
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1 AND pid <> pg_backend_pid()",
            database,
        )
        await connection.execute(f'DROP DATABASE IF EXISTS "{database}"')
    finally:
        await connection.close()


async def inspect(database: str, contract: object) -> None:
    connection = await asyncpg.connect(ADMIN_URL.rsplit("/", 1)[0] + f"/{database}")
    try:
        actual_tables = {
            row["table_name"]
            for row in await connection.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
        }
        expected_tables = set(contract.TABLES)
        assert expected_tables <= actual_tables, expected_tables - actual_tables

        for table in contract.TABLES:
            columns = {
                row["column_name"]: row["udt_name"]
                for row in await connection.fetch(
                    "SELECT column_name, udt_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = $1",
                    table,
                )
            }
            expected_columns = {"id", "created_at", "updated_at"}
            expected_columns.update(definition.split()[0] for definition in contract.COLUMNS.get(table, ()))
            assert expected_columns <= columns.keys(), f"{table}: missing {expected_columns - columns.keys()}"
            assert columns["id"] == "uuid", f"{table}.id is {columns['id']}, not uuid"

        constraints = {
            row["conname"]
            for row in await connection.fetch(
                "SELECT conname FROM pg_constraint WHERE connamespace = 'public'::regnamespace"
            )
        }
        expected_constraints = {entry[0] for entry in contract.FOREIGN_KEYS}
        expected_constraints.update(entry[0] for entry in contract.UNIQUES)
        expected_constraints.update(entry[0] for entry in contract.CHECKS)
        assert expected_constraints <= constraints, expected_constraints - constraints

        indexes = {
            row["indexname"]
            for row in await connection.fetch("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        }
        expected_indexes = {entry[0] for entry in contract.INDEXES}
        assert expected_indexes <= indexes, expected_indexes - indexes
    finally:
        await connection.close()


def main() -> int:
    database = f"control_plane_r2_{uuid4().hex}"
    contract = migration_contract()
    asyncio.run(create_database(database))
    try:
        config = alembic_config(database)
        command.upgrade(config, "head")
        asyncio.run(inspect(database, contract))
        command.downgrade(config, "0003_durable_worker_jobs")
        command.upgrade(config, "head")
        asyncio.run(inspect(database, contract))
    finally:
        asyncio.run(drop_database(database))
    print("Control-plane schema contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
