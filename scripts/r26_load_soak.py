"""Bounded R26 API/PostgreSQL/MongoDB load and soak qualification."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import resource
import statistics
import time
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from pymongo import AsyncMongoClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.worker.durable import DurableJobWorker, ExecutionContext, Job, JobRepository


ROOT = Path(__file__).resolve().parents[1]
QUALIFICATION_SECONDS = 60
DEVELOPER_SECONDS = 10


async def main(duration: int, developer: bool) -> None:
    minimum = DEVELOPER_SECONDS if developer else QUALIFICATION_SECONDS
    if duration < minimum:
        raise RuntimeError(f"duration must be at least {minimum} seconds")
    database_url = required("DATABASE_URL")
    api_url = required("R24_API_URL").rstrip("/")
    mongo_uri = required("R24_MONGO_ROOT_URI")
    values = read_env(ROOT / "artifacts" / "generated" / "r24-playwright.env")
    target_id = values["R24_TARGET_ID"]
    engine = create_async_engine(database_url, pool_size=4, max_overflow=2, pool_timeout=5)
    mongo: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
        mongo_uri, maxPoolSize=8, minPoolSize=1, waitQueueTimeoutMS=2_000
    )
    latencies: list[float] = []
    failures: list[str] = []
    max_pg_connections = 0
    max_queue_depth = 0
    max_mongo_connections = 0
    max_waiting_locks = 0
    max_pool_wait_ms = 0.0
    max_transaction_ms = 0.0
    recovered_transport_errors = 0
    run_creation_latencies: list[float] = []
    claim_latencies: list[float] = []
    soak_jobs: dict[str, float] = {}
    completed_soak_jobs: set[str] = set()
    task_count_before = len([task for task in asyncio.all_tasks() if not task.done()])
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    process_time_before = time.process_time()
    mongo_connections_start = await mongo_connection_count(mongo_uri)
    async with engine.connect() as connection:
        queue_depth_before = int(
            await connection.scalar(
                text("SELECT count(*) FROM jobs WHERE status IN ('PENDING','RUNNING')")
            )
            or 0
        )
        deadlocks_before = int(
            await connection.scalar(
                text("SELECT deadlocks FROM pg_stat_database WHERE datname=current_database()")
            )
            or 0
        )
    async with httpx.AsyncClient(base_url=api_url, timeout=10) as client:
        login = await client.post(
            "/auth/login",
            json={"email": values["R24_OPERATOR_EMAIL"], "password": values["R24_PASSWORD"]},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        async def create_one(position: int) -> str:
            started = time.perf_counter()
            response = await client.post(
                "/api/v1/runs",
                headers=headers,
                json={
                    "target_id": target_id,
                    "deployment_mode": "APPROVAL_CONTROLLED",
                    "primary_metric_key": "p99_latency_ms",
                },
            )
            response.raise_for_status()
            run_creation_latencies.append((time.perf_counter() - started) * 1000)
            return str(response.json()["run_id"])

        created = await asyncio.gather(*(create_one(position) for position in range(32)))
        if len(created) != len(set(created)):
            raise AssertionError("concurrent API run creation returned duplicate identities")
        async with engine.connect() as connection:
            atomic = await connection.scalar(
                text(
                    "SELECT count(*) FROM optimization_runs r JOIN jobs j "
                    "ON j.optimization_run_id=r.id WHERE r.id=ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": created},
            )
            duplicate = await connection.scalar(
                text(
                    "SELECT count(*) FROM (SELECT optimization_run_id FROM jobs "
                    "WHERE optimization_run_id=ANY(CAST(:ids AS uuid[])) "
                    "GROUP BY optimization_run_id HAVING count(*)<>1) x"
                ),
                {"ids": created},
            )
        if int(atomic or 0) != 32 or int(duplicate or 0) != 0:
            raise AssertionError("run/job creation was not atomic and one-to-one")

        deadline = time.monotonic() + duration
        soak_tag = f"r26-soak-{uuid4().hex}"
        repository = JobRepository(engine, lease_duration=timedelta(seconds=5))

        async def soak_handler(job: Job, _context: ExecutionContext) -> None:
            await mongo.get_database("admin").command({"ping": 1})
            completed_soak_jobs.add(job.id)
            claim_latencies.append((time.perf_counter() - soak_jobs[job.id]) * 1000)

        async def durable_job_loop(worker_name: str) -> None:
            worker = DurableJobWorker(repository, worker_name, payload_tag=soak_tag)
            while time.monotonic() < deadline:
                job_id = await repository.enqueue(
                    {"soak": True, "_queue_tag": soak_tag}
                )
                soak_jobs[str(job_id)] = time.perf_counter()
                if not await worker.run_once(soak_handler):
                    failures.append("DurableJobNotClaimed")
                await asyncio.sleep(0.1)

        async def poller(worker: int) -> None:
            nonlocal max_pg_connections, max_queue_depth, max_mongo_connections
            nonlocal max_waiting_locks
            nonlocal max_pool_wait_ms, max_transaction_ms
            nonlocal recovered_transport_errors
            while time.monotonic() < deadline:
                for path in (
                    "/api/v1/runs?limit=100",
                    f"/api/v1/runs/{values['R24_SUCCESS_RUN_ID']}",
                    "/api/v1/approvals?limit=100",
                    "/api/v1/experience?limit=100",
                ):
                    started = time.perf_counter()
                    try:
                        response, recovered = await get_poll_response(
                            client, path, headers=headers
                        )
                        recovered_transport_errors += int(recovered)
                        response.raise_for_status()
                        latencies.append((time.perf_counter() - started) * 1000)
                        body = response.json()
                        if path.startswith("/api/v1/runs?") and isinstance(body, dict):
                            records = body.get("records")
                            if isinstance(records, list) and len(records) > 100:
                                failures.append("UnboundedRunList")
                    except Exception as error:  # safe type-only evidence
                        failures.append(type(error).__name__)
                await mongo.get_database("admin").command({"ping": 1})
                if worker == 0:
                    status = await mongo.get_database("admin").command({"serverStatus": 1})
                    max_mongo_connections = max(
                        max_mongo_connections, int(status.get("connections", {}).get("current", 0))
                    )
                    pool_started = time.perf_counter()
                    async with engine.connect() as connection:
                        max_pool_wait_ms = max(
                            max_pool_wait_ms,
                            (time.perf_counter() - pool_started) * 1000,
                        )
                        transaction_started = time.perf_counter()
                        max_pg_connections = max(
                            max_pg_connections,
                            int(
                                await connection.scalar(
                                    text(
                                        "SELECT count(*) FROM pg_stat_activity "
                                        "WHERE datname=current_database()"
                                    )
                                )
                                or 0
                            ),
                        )
                        max_queue_depth = max(
                            max_queue_depth,
                            int(
                                await connection.scalar(
                                    text("SELECT count(*) FROM jobs WHERE status IN ('PENDING','RUNNING')")
                                )
                                or 0
                            ),
                        )
                        max_waiting_locks = max(
                            max_waiting_locks,
                            int(
                                await connection.scalar(
                                    text("SELECT count(*) FROM pg_locks WHERE NOT granted")
                                )
                                or 0
                            ),
                        )
                        max_transaction_ms = max(
                            max_transaction_ms,
                            (time.perf_counter() - transaction_started) * 1000,
                        )
                await asyncio.sleep(0.2)

        await asyncio.gather(
            *(poller(index) for index in range(6)),
            durable_job_loop("r26-soak-worker-a"),
            durable_job_loop("r26-soak-worker-b"),
        )

    async with engine.connect() as connection:
        queue_depth_after = int(
            await connection.scalar(
                text("SELECT count(*) FROM jobs WHERE status IN ('PENDING','RUNNING')")
            )
            or 0
        )
        deadlocks_after = int(
            await connection.scalar(
                text("SELECT deadlocks FROM pg_stat_database WHERE datname=current_database()")
            )
            or 0
        )
        persisted_soak_completed = int(
            await connection.scalar(
                text(
                    "SELECT count(*) FROM jobs WHERE payload->>'_queue_tag'=:tag "
                    "AND status='COMPLETED'"
                ),
                {"tag": soak_tag},
            )
            or 0
        )
    usage_after = resource.getrusage(resource.RUSAGE_SELF)
    process_cpu_seconds = time.process_time() - process_time_before
    await mongo.close()
    await engine.dispose()
    # Both async drivers own monitor/pool tasks while their clients are open.
    # Give cancellation callbacks a loop turn before checking for real leaks.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    mongo_connections_end = await mongo_connection_count(mongo_uri)
    task_count_after = len([task for task in asyncio.all_tasks() if not task.done()])
    if failures:
        raise AssertionError(f"soak had {len(failures)} request failures: {sorted(set(failures))}")
    if not latencies:
        raise AssertionError("soak recorded no API samples")
    ordered = sorted(latencies)
    p95 = ordered[int((len(ordered) - 1) * 0.95)]
    if p95 > 2_000:
        raise AssertionError(f"API p95 latency exceeded 2s: {p95:.2f}ms")
    if max_pg_connections > 20:
        raise AssertionError(f"PostgreSQL connection budget exceeded: {max_pg_connections}")
    if queue_depth_after != queue_depth_before + 32:
        raise AssertionError(
            "queue depth changed outside the 32 intentionally created load runs: "
            f"{queue_depth_before} -> {queue_depth_after}"
        )
    if deadlocks_after != deadlocks_before or max_waiting_locks:
        raise AssertionError(
            f"database contention observed: deadlocks={deadlocks_before}->{deadlocks_after}, "
            f"waiting_locks={max_waiting_locks}"
        )
    if (
        persisted_soak_completed != len(soak_jobs)
        or completed_soak_jobs != set(soak_jobs)
    ):
        raise AssertionError(
            "durable soak jobs were lost, duplicated, or left incomplete: "
            f"created={len(soak_jobs)}, handled={len(completed_soak_jobs)}, "
            f"persisted={persisted_soak_completed}"
        )
    if task_count_after != task_count_before:
        raise AssertionError(
            f"async task leak detected: {task_count_before} -> {task_count_after}"
        )
    if mongo_connections_end > mongo_connections_start + 2:
        raise AssertionError(
            "MongoDB connections did not return to the bounded reused-client baseline: "
            f"{mongo_connections_start} -> {mongo_connections_end}"
        )
    artifact = {
        "status": "PASS",
        "mode": "developer" if developer else "qualification",
        "duration_seconds": duration,
        "api_samples": len(latencies),
        "api_mean_ms": statistics.mean(latencies),
        "api_p95_ms": p95,
        "run_creation_p95_ms": percentile95(run_creation_latencies),
        "worker_claim_p95_ms": percentile95(claim_latencies),
        "queue_wait_p95_ms": percentile95(claim_latencies),
        "max_pool_wait_ms": max_pool_wait_ms,
        "max_transaction_ms": max_transaction_ms,
        "failures": 0,
        "recovered_transport_errors": recovered_transport_errors,
        "concurrent_runs": 32,
        "max_postgres_connections": max_pg_connections,
        "max_mongo_connections": max_mongo_connections,
        "mongo_connections_start": mongo_connections_start,
        "mongo_connections_end": mongo_connections_end,
        "max_queue_depth": max_queue_depth,
        "queue_depth_before": queue_depth_before,
        "queue_depth_after": queue_depth_after,
        "deadlocks_before": deadlocks_before,
        "deadlocks_after": deadlocks_after,
        "max_waiting_locks": max_waiting_locks,
        "mongo_client_instances": 1,
        "durable_soak_jobs": len(soak_jobs),
        "worker_failures": 0,
        "process_cpu_seconds": process_cpu_seconds,
        "process_cpu_percent_of_one_core": process_cpu_seconds / duration * 100,
        "max_rss_start": usage_before.ru_maxrss,
        "max_rss_end": usage_after.ru_maxrss,
        "max_rss_delta": usage_after.ru_maxrss - usage_before.ru_maxrss,
        "async_tasks_start": task_count_before,
        "async_tasks_end": task_count_after,
    }
    output = ROOT / "artifacts" / "generated" / "r26-soak.json"
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(
        f"R26 SOAK PASS: {duration}s, {len(latencies)} requests, "
        f"p95={p95:.2f}ms, pg_max={max_pg_connections}, mongo_max={max_mongo_connections}"
    )


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def percentile95(values: list[float]) -> float:
    if not values:
        raise AssertionError("qualification metric has no samples")
    ordered = sorted(values)
    return ordered[int((len(ordered) - 1) * 0.95)]


async def mongo_connection_count(uri: str) -> int:
    """Observe server connections with an identical disposable client."""
    observer: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
        uri,
        maxPoolSize=1,
        minPoolSize=0,
        serverSelectionTimeoutMS=2_000,
    )
    try:
        status = await observer.get_database("admin").command({"serverStatus": 1})
        return int(status.get("connections", {}).get("current", 0))
    finally:
        await observer.close()
        await asyncio.sleep(0)
        await asyncio.sleep(0)


async def get_poll_response(
    client: httpx.AsyncClient,
    path: str,
    *,
    headers: dict[str, str],
) -> tuple[httpx.Response, bool]:
    """Retry one transport disconnect for an idempotent dashboard GET."""
    try:
        return await client.get(path, headers=headers), False
    except httpx.TransportError:
        await asyncio.sleep(0.05)
        return await client.get(path, headers=headers), True


def read_env(path: Path) -> dict[str, str]:
    return {
        key: value
        for line in path.read_text().splitlines()
        for key, separator, value in [line.partition("=")]
        if separator
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=QUALIFICATION_SECONDS)
    parser.add_argument("--developer", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.duration, arguments.developer))
