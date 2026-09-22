"""Controlled CommerceBench execution against a real MongoDB target."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from pymongo import MongoClient
from pymongo.database import Database

from app.metrics.collector import CounterDeltas, ServerCounterSample, derive_counter_deltas
from benchmarks.commercebench import DatasetSnapshot, WorkloadKind, WorkloadShape, mixed_workload_shapes
from benchmarks.reset import ResetPlan, build_reset_plan, delta_reset, observed_digest
from benchmarks.runner import BenchmarkArm, BenchmarkArmOrder


@dataclass(frozen=True)
class BenchmarkExecutionSettings:
    """Warmup/measurement configuration in exactly one unit.

    ``SMOKE``/``STANDARD`` use operation counts.  The frozen PUBLICATION
    profile is time-based (60 s warmup, 120 s measurement); those values are
    seconds and must never be reinterpreted as operation counts.
    """

    warmup_operations: int | None = 10
    measurement_operations: int | None = 50
    warmup_seconds: float | None = None
    measurement_seconds: float | None = None
    operation_timeout_ms: float = 1_000.0

    def __post_init__(self) -> None:
        duration_mode = self.warmup_seconds is not None or self.measurement_seconds is not None
        count_mode = self.warmup_operations is not None or self.measurement_operations is not None
        if duration_mode and count_mode:
            raise ValueError("benchmark settings must use either operation counts or durations, not both")
        if duration_mode:
            if self.warmup_seconds is None or self.measurement_seconds is None:
                raise ValueError("duration-based measurement requires both warmup_seconds and measurement_seconds")
            if self.warmup_seconds < 0:
                raise ValueError("warmup_seconds cannot be negative")
            if self.measurement_seconds <= 0:
                raise ValueError("measurement_seconds must be positive")
            return
        if not count_mode:
            raise ValueError("benchmark settings require operation counts or durations")
        if self.warmup_operations is None or self.measurement_operations is None:
            raise ValueError("operation-count measurement requires both warmup_operations and measurement_operations")
        if self.warmup_operations < 0:
            raise ValueError("warmup_operations cannot be negative")
        if self.measurement_operations <= 0:
            raise ValueError("measurement_operations must be positive")

    @property
    def duration_based(self) -> bool:
        """Whether this configuration measures wall-clock seconds instead of counts."""
        return self.measurement_seconds is not None


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
    reset_implementation: str = "full"
    reset_fingerprint: str | None = None


class JsonTrialResultStore:
    """Persist typed trial records as true JSON Lines (one record per line).

    The historical implementation wrote a JSON array to a ``.jsonl`` path,
    which is not valid JSONL.  Evidence files must be parseable one record at
    a time so parsers and partial/running evidence remain valid.
    """

    def __init__(self, path: Path, append: bool = False) -> None:
        self._path = path
        self._append = append

    def persist(self, records: tuple[RealBenchmarkRunRecord, ...]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if self._append else "w"
        with self._path.open(mode, encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(asdict(record), sort_keys=True, separators=(",", ":")) + "\n")


class RealMongoBenchmarkExecutor:
    """Restore, verify, warm up, and measure AB/BA CommerceBench trials on MongoDB.

    Per-arm reset uses the provably-equivalent delta strategy by default; the
    first materialization is always a full restore that establishes the pristine
    state and is verified by a content digest.
    """

    def __init__(
        self,
        uri: str,
        database_name: str = "commercebench",
        settings: BenchmarkExecutionSettings = BenchmarkExecutionSettings(),
        reset_implementation: str = "delta",
    ) -> None:
        if reset_implementation not in ("delta", "full"):
            raise ValueError("reset_implementation must be 'delta' or 'full'")
        self._uri = uri
        self._database_name = database_name
        self._settings = settings
        self._reset_implementation = reset_implementation
        self._reset_plan: ResetPlan | None = None
        self._reset_plan_fingerprint: str | None = None
        self._reset_seconds: list[float] = []

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
                reset = self._reset(database, snapshot)
                if arm is BenchmarkArm.CANDIDATE and candidate_setup is not None:
                    candidate_setup(database)
                measurement = self._measure(database)
                records[arm] = RealBenchmarkRunRecord(
                    pair_id, arm, arm_order, snapshot.seed, snapshot.generator_version, snapshot.fingerprint,
                    snapshot.fingerprint, environment, measurement,
                    reset_implementation=str(reset["reset_implementation"]),
                    reset_fingerprint=str(reset["reset_fingerprint"]),
                )
        baseline, candidate = records[BenchmarkArm.BASELINE], records[BenchmarkArm.CANDIDATE]
        if baseline.initial_dataset_fingerprint != candidate.initial_dataset_fingerprint:
            raise RuntimeError("benchmark arms did not begin from equivalent dataset state")
        if baseline.reset_fingerprint != candidate.reset_fingerprint:
            raise RuntimeError("benchmark arms did not begin from equivalent reset fingerprint")
        result_store.persist((baseline, candidate))
        return baseline, candidate

    def reset_timing_summary(self) -> dict[str, object]:
        """Recorded per-arm reset timings for manifest persistence."""
        samples = self._reset_seconds
        return {
            "reset_implementation": self._reset_implementation,
            "reset_count": len(samples),
            "reset_seconds_total": sum(samples),
            "reset_seconds_mean": (sum(samples) / len(samples)) if samples else None,
            "reset_seconds_max": max(samples) if samples else None,
        }

    def _reset(self, database: Database[Any], snapshot: DatasetSnapshot) -> dict[str, object]:
        """Return the database to the exact pristine starting state before an arm."""
        started = time.perf_counter()
        try:
            return self._reset_inner(database, snapshot)
        finally:
            self._reset_seconds.append(time.perf_counter() - started)

    def _reset_inner(self, database: Database[Any], snapshot: DatasetSnapshot) -> dict[str, object]:
        if self._reset_implementation == "delta":
            if self._reset_plan is None or self._reset_plan_fingerprint != snapshot.fingerprint:
                self._restore(database, snapshot)
                self._reset_plan = build_reset_plan(snapshot)
                self._reset_plan_fingerprint = snapshot.fingerprint
                pristine = observed_digest(database, self._reset_plan)
                if pristine != self._reset_plan.expected_digest:
                    raise RuntimeError("materialized dataset does not match the frozen pristine state")
            return delta_reset(database, self._reset_plan)
        fingerprint = self._restore(database, snapshot)
        return {"reset_implementation": "full", "reset_fingerprint": fingerprint, "dropped_optimizer_indexes": [], "removed_synthetic_events": 0}

    def environment_fingerprint(self) -> dict[str, str]:
        """Persistable MongoDB environment facts for experiment manifests."""
        with MongoClient(self._uri, serverSelectionTimeoutMS=5_000) as client:
            return self._verify_environment(client)

    def materialize_and_count(self, snapshot: DatasetSnapshot) -> dict[str, int]:
        """Materialize a snapshot and return observed counts from the live target.

        Used to prove actual dataset materialization before authoritative
        measurement rather than trusting a profile enum.  Establishes the
        pristine state and reset plan used by subsequent delta resets.
        """
        with MongoClient(self._uri, serverSelectionTimeoutMS=5_000) as client:
            self._verify_environment(client)
            database = client[self._database_name]
            self._restore(database, snapshot)
            self._reset_plan = build_reset_plan(snapshot)
            self._reset_plan_fingerprint = snapshot.fingerprint
            pristine = observed_digest(database, self._reset_plan)
            if pristine != self._reset_plan.expected_digest:
                raise RuntimeError("materialized dataset does not match the frozen pristine state")
            return {name: int(database[name].count_documents({})) for name, _ in snapshot.collections}

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
                # Collections were just dropped, so unordered insertion cannot
                # produce duplicates; it materially shortens publication-scale
                # restores while preserving the exact restored document set.
                database[name].insert_many(list(documents), ordered=False)
        counts = {name: database[name].count_documents({}) for name, _ in snapshot.collections}
        if counts != snapshot.collection_counts:
            raise RuntimeError(f"dataset restoration counts differ: {counts}")
        return snapshot.fingerprint

    def _measure(self, database: Database[Any]) -> RealBenchmarkMeasurement:
        shapes = mixed_workload_shapes()
        schedule = tuple(shape for shape in shapes for _ in range(shape.weight))
        settings = self._settings
        if settings.duration_based:
            warmup_operations = None
            warmup_seconds = settings.warmup_seconds
            measurement_operations = None
            measurement_seconds = settings.measurement_seconds
        else:
            warmup_operations = settings.warmup_operations
            warmup_seconds = None
            measurement_operations = settings.measurement_operations
            measurement_seconds = None
        position = self._run_window(
            database, schedule, 0, operations=warmup_operations, seconds=warmup_seconds, record=False
        )[0]
        start_counters = _server_counters(database)
        started = time.perf_counter()
        _, latencies, errors, timeouts = self._run_window(
            database, schedule, position, operations=measurement_operations, seconds=measurement_seconds, record=True
        )
        elapsed_seconds = time.perf_counter() - started
        end_counters = _server_counters(database)
        successful = len(latencies)
        return RealBenchmarkMeasurement(
            successful, errors, timeouts, elapsed_seconds,
            successful / elapsed_seconds if elapsed_seconds else 0.0,
            _percentile(latencies, 50), _percentile(latencies, 95), _percentile(latencies, 99),
            derive_counter_deltas(start_counters, end_counters, successful),
        )

    def _run_window(
        self,
        database: Database[Any],
        schedule: tuple[WorkloadShape, ...],
        start_position: int,
        *,
        operations: int | None,
        seconds: float | None,
        record: bool,
    ) -> tuple[int, list[float], int, int]:
        """Execute the frozen schedule for a count or a wall-clock duration.

        Positions advance monotonically across warmup and measurement so
        synthetic write keys never collide between the two windows.
        """
        latencies: list[float] = []
        errors = timeouts = 0
        position = start_position
        deadline = None if seconds is None else time.perf_counter() + seconds
        remaining = None if seconds is not None else (operations or 0)
        while _window_open(deadline, remaining):
            if remaining is not None:
                remaining -= 1
            operation_started = time.perf_counter()
            try:
                self._execute(database, schedule[position % len(schedule)], position)
            except Exception:
                errors += 1
                position += 1
                continue
            if record:
                elapsed_ms = (time.perf_counter() - operation_started) * 1_000
                if elapsed_ms > self._settings.operation_timeout_ms:
                    timeouts += 1
                else:
                    latencies.append(elapsed_ms)
            position += 1
        return position, latencies, errors, timeouts

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


def _window_open(deadline: float | None, remaining: int | None) -> bool:
    """Whether a duration or operation-count measurement window still accepts work."""
    if remaining is not None:
        return remaining > 0
    if deadline is not None:
        return time.perf_counter() < deadline
    return False


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100
    lower, upper = int(index), min(int(index) + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)
