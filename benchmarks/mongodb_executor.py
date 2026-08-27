"""Controlled CommerceBench execution against a real MongoDB target."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, cast

from pymongo import MongoClient
from pymongo.database import Database

from app.metrics.collector import CounterDeltas, ServerCounterSample, derive_counter_deltas  # type: ignore[import-not-found]
from benchmarks.commercebench import DatasetSnapshot, WorkloadKind, WorkloadShape, mixed_workload_shapes
from benchmarks.runner import BenchmarkArm, BenchmarkArmOrder


@dataclass(frozen=True)
class BenchmarkExecutionSettings:
    warmup_operations: int = 10
    measurement_operations: int = 50
    operation_timeout_ms: float = 1_000.0


@dataclass(frozen=True)
class RealBenchmarkMeasurement:
    successful_operations: int
    error_count: int
    timeout_count: int
    elapsed_seconds: float
    throughput_successful_ops_per_second: float
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    p99_latency_ms: float | None
    counter_deltas: CounterDeltas


@dataclass(frozen=True)
class RealBenchmarkRunRecord:
    pair_id: str
    arm: BenchmarkArm
    arm_order: BenchmarkArmOrder
    seed: int
    generator_version: str
    dataset_fingerprint: str
    initial_dataset_fingerprint: str
    environment: dict[str, str]
    measurement: RealBenchmarkMeasurement


class JsonTrialResultStore:
    """Persist typed trial records as a durable JSON evidence artifact."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def persist(self, records: tuple[RealBenchmarkRunRecord, ...]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps([asdict(record) for record in records], sort_keys=True, indent=2) + "\n", encoding="utf-8")


class RealMongoBenchmarkExecutor:
    """Restore, verify, warm up, and measure AB/BA CommerceBench trials on MongoDB."""

    def __init__(self, uri: str, database_name: str = "commercebench", settings: BenchmarkExecutionSettings = BenchmarkExecutionSettings()) -> None:
        self._uri = uri
        self._database_name = database_name
        self._settings = settings

    def run_pair(
        self,
        pair_id: str,
        snapshot: DatasetSnapshot,
        result_store: JsonTrialResultStore,
        arm_order: BenchmarkArmOrder = BenchmarkArmOrder.AB,
        candidate_setup: Callable[[Database[Any]], None] | None = None,
    ) -> tuple[RealBenchmarkRunRecord, RealBenchmarkRunRecord]:
        with MongoClient(self._uri, serverSelectionTimeoutMS=5_000) as client:
            environment = self._verify_environment(client)
            database = client[self._database_name]
            arms = [BenchmarkArm.BASELINE, BenchmarkArm.CANDIDATE]
            if arm_order is BenchmarkArmOrder.BA:
                arms.reverse()
            records: dict[BenchmarkArm, RealBenchmarkRunRecord] = {}
            for arm in arms:
                restored_fingerprint = self._restore(database, snapshot)
                if arm is BenchmarkArm.CANDIDATE and candidate_setup is not None:
                    candidate_setup(database)
                measurement = self._measure(database)
                records[arm] = RealBenchmarkRunRecord(
                    pair_id, arm, arm_order, snapshot.seed, snapshot.generator_version, snapshot.fingerprint,
                    restored_fingerprint, environment, measurement,
                )
        baseline, candidate = records[BenchmarkArm.BASELINE], records[BenchmarkArm.CANDIDATE]
        if baseline.initial_dataset_fingerprint != candidate.initial_dataset_fingerprint:
            raise RuntimeError("benchmark arms did not begin from equivalent dataset state")
        result_store.persist((baseline, candidate))
        return baseline, candidate

    def _verify_environment(self, client: MongoClient[Any]) -> dict[str, str]:
        build = client.admin.command({"buildInfo": 1})
        hello = client.admin.command({"hello": 1})
        version = str(build.get("version", ""))
        if not version.startswith("8."):
            raise RuntimeError(f"CommerceBench requires MongoDB 8, found {version}")
        replica_set = str(hello.get("setName", ""))
        if not replica_set:
            raise RuntimeError("CommerceBench requires a replica-set MongoDB target")
        return {"mongodb_version": version, "replica_set": replica_set}

    def _restore(self, database: Database[Any], snapshot: DatasetSnapshot) -> str:
        for collection in snapshot.collections:
            database[collection[0]].drop()
        for name, documents in snapshot.collections:
            if documents:
                database[name].insert_many(list(documents), ordered=True)
        counts = {name: database[name].count_documents({}) for name, _ in snapshot.collections}
        if counts != snapshot.collection_counts:
            raise RuntimeError(f"dataset restoration counts differ: {counts}")
        return cast(str, snapshot.fingerprint)

    def _measure(self, database: Database[Any]) -> RealBenchmarkMeasurement:
        shapes = mixed_workload_shapes()
        schedule = tuple(shape for shape in shapes for _ in range(shape.weight))
        for position in range(self._settings.warmup_operations):
            self._execute(database, schedule[position % len(schedule)], position)
        start_counters = _server_counters(database)
        started = time.perf_counter()
        latencies: list[float] = []
        errors = timeouts = 0
        for position in range(self._settings.measurement_operations):
            operation_started = time.perf_counter()
            try:
                self._execute(database, schedule[position % len(schedule)], position)
            except Exception:
                errors += 1
                continue
            elapsed_ms = (time.perf_counter() - operation_started) * 1_000
            if elapsed_ms > self._settings.operation_timeout_ms:
                timeouts += 1
            else:
                latencies.append(elapsed_ms)
        elapsed_seconds = time.perf_counter() - started
        end_counters = _server_counters(database)
        successful = len(latencies)
        return RealBenchmarkMeasurement(
            successful, errors, timeouts, elapsed_seconds,
            successful / elapsed_seconds if elapsed_seconds else 0.0,
            _percentile(latencies, 50), _percentile(latencies, 95), _percentile(latencies, 99),
            derive_counter_deltas(start_counters, end_counters, successful),
        )

    @staticmethod
    def _execute(database: Database[Any], shape: WorkloadShape, position: int) -> None:
        customer_id, product_id, order_id = (position % 1_000) + 1, (position % 500) + 1, (position % 10_000) + 1
        if shape.name == "customer_by_id":
            database.customers.find_one({"_id": customer_id})
        elif shape.name == "product_by_category":
            database.products.find_one({"category": f"category-{position % 8}"})
        elif shape.name == "orders_by_customer":
            database.orders.find_one({"customer_id": customer_id}, sort=[("_id", -1)])
        elif shape.name == "inventory_by_product":
            database.inventory.find_one({"product_id": product_id})
        elif shape.name == "order_status_update":
            database.orders.update_one({"_id": order_id}, {"$set": {"status": "paid"}})
        elif shape.name == "inventory_decrement":
            database.inventory.update_one({"product_id": product_id}, {"$inc": {"available": -1}})
        elif shape.kind is WorkloadKind.WRITE:
            database.events.insert_one({"_id": 10_000_000 + position, "customer_id": customer_id, "event_type": "view", "sequence": 10_000_000 + position})


def _server_counters(database: Database[Any]) -> ServerCounterSample:
    status = database.command({"serverStatus": 1})
    opcounters = status.get("opcounters", {})
    network = status.get("network", {})
    memory = status.get("mem", {})
    operations = sum(float(opcounters.get(name, 0)) for name in ("insert", "query", "update", "delete", "command"))
    return ServerCounterSample(0.0, 0.0, float(memory.get("resident", 0)), 0.0, 0.0, 0.0, operations, float(network.get("bytesIn", 0)) + float(network.get("bytesOut", 0)))


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100
    lower, upper = int(index), min(int(index) + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)
